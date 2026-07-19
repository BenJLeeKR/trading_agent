# Phase 7 Subtask 1: Historical DB 정합성 이슈 후보 Inventory

## 조사 대상별 분석

### 1. translation.py

**파일**: [`src/agent_trading/services/translation.py`](src/agent_trading/services/translation.py)

#### `resolve_decision_type()` (line 135-155)
- AI 출력 `decision_type` 문자열을 `DecisionType` enum으로 매핑
- 소문자 정규화 후 매핑: `"buy"`, `"strong_buy"` → `DecisionType.BUY` (`.value = "buy"`)
- `DecisionType` enum은 소문자 값을 사용: `APPROVE = "approve"`, `BUY = "buy"`, `SELL = "sell"`, `HOLD = "hold"`, `CLOSE = "close"`, `WATCH = "watch"`, `EXIT = "exit"`, `REDUCE = "reduce"`
- 알 수 없는 값은 `DecisionType.HOLD`로 fallback (안전하지만, AI 출력 drift 시 HOLD로 잘못 분류될 가능성)

#### `normalize_decision_type()` (line 206-246)
- `resolve_decision_type()`과 **다른 정규화 방식을 사용**: 대문자 반환 (`"APPROVE"`, `"BUY"`, `"SELL"`, `"HOLD"` 등)
- 이 함수는 `translation.py`의 `__all__`에 export되어 있으나, 실제 persistence path에서는 사용되지 않음
- **잠재적 혼란**: 두 함수가 서로 다른 케이스(소문자 vs 대문자)를 반환하므로, 추후 잘못 사용될 경우 데이터 정합성 깨짐

#### `build_submit_order_request_from_decision()` (line 49-124)
- `OrderIntent` → `SubmitOrderRequest` 변환
- `decision_type`이 `actionable_types`에 없으면 `None` 반환
- `actionable_types`는 대문자 집합: `{"APPROVE", "BUY", "SELL", "EXIT", "REDUCE", "WATCH"}`
- 그런데 `decision_type`이 실제로 대문자인지 소문자인지는 `OrderIntent`를 생성하는 caller에 의존
- `DecisionType` enum `.value`는 소문자이므로, 이 검증이 의도대로 동작하는지 추적 필요

#### Historical data 영향 평가
- **낮음**: 현재 persistence path는 `resolve_decision_type()`을 통해 일관되게 소문자 `DecisionType` enum 값을 저장
- `normalize_decision_type()`이 persistence path에서 사용되지 않으므로 대소문자 혼란은 발생하지 않음

---

### 2. DB Repository 코드

#### `PostgresTradeDecisionRepository` ([`src/agent_trading/repositories/postgres/trade_decisions.py`](src/agent_trading/repositories/postgres/trade_decisions.py))

- **line 83**: `decision.decision_type.value if decision.decision_type else None,`
  - `DecisionType` enum의 `.value`를 사용 → 소문자 ("approve", "buy", "sell" 등) 저장
  - `decision_type`이 `None`이면 `NULL` 저장 → CHECK 제약이 없으므로 허용됨
- **line 84**: `decision.side.value if decision.side else None,`
  - `OrderSide` enum → 소문자 ("buy", "sell")
- Migration 0004에서 `decision_type` 컬럼은 `DEFAULT 'approve'` (소문자)로 추가됨 → 일관성 유지

#### `PostgresExecutionAttemptRepository` ([`src/agent_trading/repositories/postgres/execution_attempts.py`](src/agent_trading/repositories/postgres/execution_attempts.py))

- **line 42**: `attempt.status`를 직접 문자열로 저장 (enum 변환 없이 raw string)
- `status` 필드는 `VARCHAR(32)`로 CHECK 제약이 없음 → `'running'`, `'stopped'`, `'submitted'`, `'failed'`, `'non_trade'`, `'reconcile_required'` 외의 값도 저장 가능
- **line 45**: `phase_trace` JSONB 직렬화: `json.dumps(attempt.phase_trace) if attempt.phase_trace is not None else None`
- `update_status()` (line 63-93): `status`를 직접 UPDATE → audit trail 부재로 이전 상태 추적 불가
- **잠재적 문제**: `status` 값의 validation 부재로 인한 데이터 정합성 저하 가능성

#### `PostgresBrokerOrderRepository` ([`src/agent_trading/repositories/postgres/broker_orders.py`](src/agent_trading/repositories/postgres/broker_orders.py))

- 단순 CRUD, 복잡한 매핑 로직 없음
- `broker_status`는 `VARCHAR(64)`로 자유 형식 → broker별 상태값 불일치 가능성
- **영향 낮음**: 주문 상태는 `order_requests.status`가 단일 truth이므로 broker_orders는 보조 정보

#### Historical data 영향 평가
- **중간**: `execution_attempts.status` 검증 부재는 Phase 4 이후 데이터에 영향
- `trade_decisions.decision_type`은 enum → string 변환이 일관되므로 문제 없음

---

### 3. 기존 Backfill 스크립트

5개의 기존 backfill 스크립트를 분석하여 패턴과 목적을 파악했습니다.

#### [`scripts/backfill_expired_market_sell_orders.py`](scripts/backfill_expired_market_sell_orders.py)
- **목적**: `expired` 상태로 잘못 마킹된 MARKET SELL 주문을 position-delta truth로 복구
- **트리거**: 특정 조건(24시간 내, broker_native_order_id 존재, expired 상태)의 주문을 `OrderSyncService.recover_expired_sell_by_position()`으로 복구
- **패턴**: 쿼리 → 서비스 호출 → 상태 변경. `--dry-run` / `--limit` 지원

#### [`scripts/backfill_external_events_metadata.py`](scripts/backfill_external_events_metadata.py)
- **목적**: 기존 `external_events` 행에 `metadata` JSONB 보강 (corp_cls, corp_code, stock_code)
- **트리거**: P0 정책 변경으로 신규 이벤트는 metadata를 저장하지만, 기존 902건은 NULL
- **패턴**: SELECT → 각 행별 로직 처리 → UPDATE. `--apply`로 실제 실행

#### [`scripts/backfill_external_events_symbol.py`](scripts/backfill_external_events_symbol.py)
- **목적**: NULL-symbol OpenDART 이벤트에 `symbol` 보강 (corp_code → stock_code resolve)
- **트리거**: OpenDART API가 stock_code를 빈 값으로 반환하는 이슈
- **패턴**: 외부 API 호출 필요. `--apply`로 실제 실행

#### [`scripts/backfill_identifier_codes.py`](scripts/backfill_identifier_codes.py)
- **목적**: `broker_account_code`, `account_code`, `account_masked` 컬럼 backfill
- **트리거**: Migration 0010에서 nullable 컬럼 추가되었으나 기존 행은 NULL
- **패턴**: 순수 SQL UPDATE (idempotent, `WHERE ... IS NULL`). `--dry-run` 지원

#### [`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py)
- **목적**: RECONCILE_REQUIRED로 stuck된 주문에 reconciliation run 생성
- **트리거**: 정책 변경으로 reconciliation trigger 필요
- **패턴**: 서비스 호출 (재사용/중복 방지). `--dry-run`, `--limit`, `--order-id` 등 다양한 옵션

#### 공통 패턴
1. **idempotent** (`WHERE ... IS NULL` 또는 `IS DISTINCT FROM`)
2. **dry-run 모드** 지원 (기본값)
3. **트랜잭션 단위** 실행
4. **로깅** 및 summary 출력
5. 복잡한 비즈니스 로직은 서비스 레이어 호출, 단순 SQL은 직접 UPDATE

---

### 4. DB Migration 영향

32개 migration 파일 중 주요 변경사항의 old data 영향 분석:

#### [`0013_add_source_type_to_trade_decisions.sql`](db/migrations/0013_add_source_type_to_trade_decisions.sql)
- `source_type VARCHAR(32) NULL` 추가. 기존 행은 `NULL`
- **영향**: Migration 0013 이전에 생성된 모든 `trade_decisions`는 `source_type = NULL`
- `source_type`은 "core", "held_position", "event_overlay", "market_overlay", "manual" 값 중 하나여야 함
- `NULL` 행은 분석/필터링에서 누락될 수 있음
- **회복 가능**: `decision_context_id`를 통해 `source_type` 추론 가능

#### [`0017_add_position_amounts.sql`](db/migrations/0017_add_position_amounts.sql)
- `position_snapshots`에 `purchase_amount`, `evaluation_amount` 추가
- 기존 행은 NULL → 분석/리포트에서 누락
- **영향 낮음**: 부가 정보 필드

#### [`0022_add_phase_trace_to_trade_decisions.sql`](db/migrations/0022_add_phase_trace_to_trade_decisions.sql)
- `trade_decisions`에 `phase_trace JSONB` 추가 (bridge 기간)
- **영향**: migration 0022와 0026 사이에 생성된 행은 `phase_trace`가 `trade_decisions`에 저장됨

#### [`0023_add_execution_attempts.sql`](db/migrations/0023_add_execution_attempts.sql)
- `execution_attempts` 테이블 신규 생성
- `status VARCHAR(32) NOT NULL DEFAULT 'running'` — CHECK 제약 없음
- **영향**: 이후 모든 execution_attempt 데이터는 이 테이블에 저장

#### [`0026_drop_bridge_columns_from_trade_decisions.sql`](db/migrations/0026_drop_bridge_columns_from_trade_decisions.sql)
- `pipeline_stop_phase`, `pipeline_stop_reason`, `pipeline_stopped_at`, `phase_trace` 컬럼 삭제
- **Data loss 가능성**: bridge 기간 동안 `trade_decisions.phase_trace`에 저장된 데이터가 삭제됨
- 단, execution_attempts 테이블로 동시에 기록되었다면 중복 없음
- **영향 확인 필요**: bridge 기간(0022 적용 후 0026 적용 전)에 생성된 trade_decisions 중 execution_attempts에 대응 레코드가 없는 경우 데이터 유실

#### [`0027_add_snapshot_sync_run_id.sql`](db/migrations/0027_add_snapshot_sync_run_id.sql)
- `position_snapshots`, `cash_balance_snapshots`에 `snapshot_sync_run_id` FK 추가
- 기존 행은 NULL → same-run alignment 불가
- **영향 낮음**: 신규 기능, 기존 데이터와 무관

---

### 5-9. 기타 영역

#### Phase 6: `recorder.py` agent_name 정규화 ([`src/agent_trading/services/ai_agents/recorder.py`](src/agent_trading/services/ai_agents/recorder.py))

- **line 123-130**: `structured_output["agent_name"]`이 `agent_type`과 다르면 `agent_type`으로 덮어씀
- 이 정규화가 적용되기 전에 저장된 `agent_runs.structured_output_json`의 `agent_name`은 LLM 출력 그대로 저장됨
- **영향 범위**: Phase 6 이전에 생성된 모든 agent_runs
- **영향도**: JSONB 내부 필드이므로 query/filter에 직접적 영향 없음. 단, Admin UI에서 `agent_name`으로 필터링할 때 누락 가능성

#### Phase 5i-5: BUY Sizing requested_quantity cap ([`src/agent_trading/services/sizing_engine.py`](src/agent_trading/services/sizing_engine.py))

- **`_resolve_buy_target_quantity()`** (line 202-251): 현금 할당 기반 수량 계산 (20% of effective cash)
- 이 함수가 도입되기 전에는 `requested_quantity`가 cap되어 `1`로 고정되었을 가능성
- **line 249**: `if target_qty < 1: target_qty = 1` — 최소 1주 보장
- **영향**: cap 제거 전 BUY 결정의 `trade_decisions.quantity`가 `1`로 잘못 저장됨
- **`min_entry_threshold`** (line 453-463): `_MIN_ENTRY_VALUE_FOR_NEW_POSITION = 500000` (50만원)
  - 이 threshold 적용 전에는 저가주에 대한 신규 포지션 결정이 검증 없이 통과됨
  - threshold 적용 후에는 50만원 미만 진입이 차단되지만, 이전 결정은 그대로 남아있음
  - 단, 이는 정합성 이슈라기보다 정책 변경에 따른 자연스러운 현상

#### `trading.order_requests` 테이블 ([`db/migrations/0001_initial_schema.sql`](db/migrations/0001_initial_schema.sql) line 286-330)

- **status** CHECK 제약: `'draft'`, `'validated'`, `'pending_submit'`, `'submitted'`, `'acknowledged'`, `'partially_filled'`, `'filled'`, `'cancel_pending'`, `'cancelled'`, `'rejected'`, `'expired'`, `'reconcile_required'`
- **side** CHECK 제약: `'buy'`, `'sell'` — 소문자 고정
- **order_type** CHECK 제약: `'market'`, `'limit'`, `'stop'`, `'stop_limit'` — 소문자 고정
- **`requested_quantity > 0`** CHECK 제약 있음
- CHECK 제약이 있으므로 status/side/order_type의 값 불일치 가능성은 **낮음**
- `status_reason_code`는 자유 형식 `VARCHAR(64)` → 일관성 없는 값 가능성 (예: "PRICE_MISMATCH" vs "price_mismatch" vs "PRICE_MISMATCH(30030)")

#### `trading.trade_decisions` 테이블

- **`decision_type`**: Migration 0004에서 `VARCHAR(32) NOT NULL DEFAULT 'approve'`로 추가됨
  - CHECK 제약 없음 → 어떤 문자열도 저장 가능
  - 현재 코드는 `DecisionType` enum 값을 통해 소문자 저장 → 일관됨
  - 하지만 과거 코드에서 다른 값을 저장했을 가능성은 배제할 수 없음
- **`source_type`**: Migration 0013에서 `VARCHAR(32) NULL`로 추가 → 이전 행은 NULL
- **`quantity`**: `NUMERIC(24, 8)` — CHECK 제약 없음. 0이나 음수도 저장 가능

#### `trading.execution_attempts` 테이블

- **`status`**: `VARCHAR(32) NOT NULL DEFAULT 'running'` — CHECK 제약 없음
- Migration 0023에서 추가된 테이블이므로 모든 데이터는 Phase 4 이후
- `update_status()`가 audit 없이 UPDATE → 실행 이력 추적 불가
- **중복 가능성**: 동일 `trade_decision_id`에 대해 여러 execution_attempt가 생성될 수 있음 (의도된 설계)

---

## 추천 Backfill 후보 (1건)

### 후보명
**BUY 결정의 `quantity=1` 왜곡 보정 (Phase 5i-5 BUY Sizing cap 잔재)**

### 원인

Phase 5i-5 이전의 BUY Sizing 로직에는 `requested_quantity`를 강제로 `1`로 고정하는 cap이 존재했습니다. 이는 초기 BUY Sizing 구현에서 과도한 주문을 방지하기 위한 안전장치였으나, 실제 의사결정 수량을 왜곡하는副作用이 있었습니다.

Phase 5i-5에서 이 cap이 제거되고 현금 할당 기반의 `_resolve_buy_target_quantity()` (20% of effective cash) 로직으로 대체되었습니다. 그러나 cap이 활성화되어 있던 기간에 생성된 `trade_decisions`의 `quantity`는 `1`로 저장되어 실제 AI 의도와 다른 왜곡된 값을 가지게 되었습니다.

**발생 기간**: Phase 5i-5 BUY Sizing 개선 작업 이전 (구체적 일자는 플랜 문서 참조)

**발생 조건**:
1. `decision_type`이 `BUY` 또는 `APPROVE` (BUY side)인 결정
2. cap이 활성화된 기간에 생성된 결정
3. 원래 `requested_quantity`가 1보다 컸던 결정

### 영향 범위

**추정 대상**: Phase 5i-5 이전에 생성된 모든 BUY 결정 중 `quantity = 1`인 행

**영향을 받는 분석/운영**:
1. **Position Sizing 분석**: 실제 AI 의도와 다른 수량으로 기록되어 position sizing 효과 분석이 왜곡됨
2. **PnL attribution**: quantity가 실제 집행 수량과 다르므로 개별 결정의 PnL 기여도 계산 오류
3. **성과 평가**: Sharpe ratio, win rate 등 성과 지표가 잘못된 position size 기반으로 계산됨
4. **Risk analytics**: VaR, exposure 계산 시 실제보다 작은 position size로 과소평가
5. **Backtesting**: 과거 결정을 재현할 때 실제 의도된 quantity를 알 수 없음

**영향 row 수**: Phase 5i-5의 적용 시점과 시스템 가동 기간에 따라 다르지만, 수십~수백 row로 추정

### 저위험 보정 방식

**방식**: 단순 UPDATE query (idempotent, preview 가능)

```sql
-- Step 1: 대상 행 확인 (preview)
SELECT td.trade_decision_id, td.decision_type, td.side, td.quantity,
       td.created_at, td.symbol
FROM trading.trade_decisions td
WHERE td.side = 'buy'
  AND td.decision_type IN ('buy', 'approve')
  AND td.quantity = 1
  AND td.created_at < 'YYYY-MM-DD'  -- Phase 5i-5 적용 일자
ORDER BY td.created_at DESC;

-- Step 2: 복구 불가능한 경우 → execution_attempts의 phase_trace에서
-- 실제 sizing 결과를 추출하여 quantity 재계산
-- (trade_decisions.quantity가 1이더라도 실제 주문은 올바른 수량으로 생성되었을 수 있음)

-- Step 2a: execution_attempts를 통해 실제 제출된 수량 확인
SELECT td.trade_decision_id, td.quantity AS stored_qty,
       o.requested_quantity AS actual_order_qty,
       td.symbol, td.created_at
FROM trading.trade_decisions td
JOIN trading.order_requests o ON o.trade_decision_id = td.trade_decision_id
WHERE td.side = 'buy'
  AND td.decision_type IN ('buy', 'approve')
  AND td.quantity = 1
  AND o.requested_quantity > 1;

-- Step 3: trade_decisions.quantity를 실제 주문 수량으로 보정
UPDATE trading.trade_decisions td
SET quantity = o.requested_quantity,
    max_order_value = o.requested_quantity * COALESCE(td.entry_price, o.requested_price)
FROM trading.order_requests o
WHERE o.trade_decision_id = td.trade_decision_id
  AND td.side = 'buy'
  AND td.decision_type IN ('buy', 'approve')
  AND td.quantity = 1
  AND o.requested_quantity > 1;
```

**안전장치**:
1. `--dry-run` 모드로 preview 후 적용 (기존 backfill 스크립트 패턴 준수)
2. `order_requests.requested_quantity`를 truth source로 활용 (실제 제출된 주문 수량)
3. `WHERE td.quantity = 1` 조건으로 idempotent 보장
4. 복구 불가능한 행(execution_attempt 없음)은 건드리지 않음

**대안**: 만약 `order_requests`와의 조인으로도 복구 불가능한 경우:
- `sizing_engine._resolve_buy_target_quantity()` 로직을 재현하여 추정치 계산
- 단, 당시의 현금 잔고/주가 데이터가 필요하므로 정확도는 떨어짐

### 기대 효과

1. **Position Sizing 분석 정확도 향상**
   - BUY 결정의 실제 의도된 position size 반영
   - cap이 제거된 이후의 정책과 일관된 데이터

2. **성과 평가 신뢰도 회복**
   - 개별 결정의 PnL 기여도가 실제 수량 기준으로 계산 가능
   - 전략별/심볼별 수익률 비교가 의미 있음

3. **리스크 메트릭 정확도 개선**
   - VaR, exposure 등의 리스크 지표가 실제 position size 반영
   - 과소평가된 리스크 노출 보정

4. **운영 오류 감소**
   - 과거 데이터 기반 분석 시 `quantity=1`로 인한 오해 방지
   - Admin UI에서 표시되는 quantity가 실제 의사결정과 일치

5. **향후 마이그레이션/리팩토링 기반**
   - 정합성 있는 과거 데이터는 데이터 모델 변경 시 신뢰할 수 있는 기준선 제공
   - 머신러닝/통계 모델 학습 데이터로 활용 가능

---

## Appendix: 추가 조사 필요 사항

### 1. Migration 0026 `phase_trace` data loss 검증
Bridge 기간(0022 적용 ~ 0026 적용)에 `trade_decisions.phase_trace`에만 저장되고 `execution_attempts`에는 없는 데이터가 있는지 확인 필요:
```sql
SELECT td.trade_decision_id, td.created_at
FROM trading.trade_decisions td
LEFT JOIN trading.execution_attempts ea ON ea.trade_decision_id = td.trade_decision_id
WHERE ea.execution_attempt_id IS NULL
  AND td.created_at BETWEEN '0022_apply_date' AND '0026_apply_date';
```

### 2. `source_type` NULL 보정
Migration 0013 이전 데이터의 `source_type = NULL` 보정:
- `decision_context_id`를 통해 source_type 추론 가능
- `agent_bundle.ai_inputs.source_type`이 결정 시점에 이미 존재했다면 복구 가능
- 단, source_type은 분석 보조 필드이므로 우선순위 낮음

### 3. `execution_attempts.status` 값 검증
CHECK 제약이 없으므로 현재 저장된 값의 분포 확인 필요:
```sql
SELECT status, COUNT(*) 
FROM trading.execution_attempts 
GROUP BY status 
ORDER BY COUNT(*) DESC;
```
