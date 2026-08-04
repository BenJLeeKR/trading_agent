# 12. KIS 실체결 기준 이동평균 실현 손익(Realized PnL) Ledger — 상세 설계

> **문서 상태**: 설계안이다. 4절의 신규 테이블 5종은 `db/migrations/0053_add_realized_pnl_ledger_tables.sql` + `0054_add_realized_pnl_support_indexes.sql`로 migration 초안이 작성되었지만 **아직 어떤 DB에도 실행되지 않았다.** 계산 엔진(5절)·repository·API·runtime 반영 코드는 **아직 구현되지 않았다.** 구현 순서와 단계 분리는 [`kis_realized_pnl_moving_average_action_plan.md`](../../40_action_plans/kis_realized_pnl_moving_average_action_plan.md)를 따른다.
> **범위**: 국내주식(KIS) 계좌의 종목별 이동평균 매입원가 기반 실현 손익. FIFO는 2절에서 비교만 하고 이번 설계는 이동평균으로 확정한다.

## 1. 도메인 문제 정의

이동평균법 실현 손익 = 매도 체결이 발생한 순간, 그 시점까지 누적된 종목별 평균 매입단가를 기준으로 `(매도가 - 평균매입단가) * 매도수량 - 수수료 - 세금`을 계산하고, 이 계산이 부분매도·분할체결·같은 날 매수/매도 교차·완전청산 후 재매수에도 일관되게 성립해야 한다는 문제다.

핵심은 **"주문 의도"가 아니라 "실제 체결"을 계산 단위로 삼는 것**이다. 하나의 `order_request`는 여러 `fill_event`로 나뉠 수 있고(부분체결), 반대로 이동평균 계산은 특정 주문에 속한 fill만 보고 판단할 수 없다(그 주문 이전에 쌓인 원가가 필요하다). 이것이 바로 2절에서 지적하는, 현재 코드가 "주문 단위로 계산"하기 때문에 원가 기반 손익이 될 수 없는 이유다.

### 1.1 현재 구현의 정확한 한계 (재확인)

[`performance_summary.py:75-135`](../../../src/agent_trading/services/performance_summary.py)의 `calc_realized_pnl_for_order()` / `_calc_per_fill_pnl()`:

```python
multiplier = -1 (BUY) / +1 (SELL)
total += fill_price * fill_quantity * multiplier - fee - tax
```

이 함수는 **하나의 `order_request`에 속한 fill들만** 인자로 받는다. SELL 주문이면 `multiplier=+1`이므로 반환값은 `매도금액 - fee - tax`, 즉 **매입원가를 전혀 참조하지 않는 매도 대금**이다. 계좌 전체 주문을 모두 합산했을 때 최종 포지션이 정확히 0인 시점에는 이 합계가 net cash flow와 같아지고 결과적으로 총 손익에 근접하지만, 종목별·기간별·부분매도 단위로는 **실현 손익이 아니라 현금흐름 근사치**다. 이 한계는 [`paper_performance_metrics.md:27-34`](../../09_paper_trading_validation/paper_performance_metrics.md)에 "per-order 기준"으로 이미 공식 문서화되어 있다.

**중요**: 이 설계 문서 전체에서 "현금흐름(cash flow)"과 "실현 손익(realized PnL)"을 같은 개념으로 쓰지 않는다. 현금흐름은 원가 차감이 없는 거래 대금의 합이고, 실현 손익은 반드시 그 시점의 매입원가를 차감한 값이다.

## 2. 기존 데이터 흐름

```
trade_decision (AI/deterministic 판단)
    │
    ▼
order_request  (side, requested_quantity, status)  ── trading.order_requests, 0001_initial_schema.sql:288-332
    │
    ▼
broker_order   (broker_native_order_id)            ── trading.broker_orders, 0001_initial_schema.sql:334-346
    │
    ├──▶ fill_events        (실시간/REST 폴링 체결)  ── trading.fill_events, 0001_initial_schema.sql:348-365
    │        생성 경로: order_sync_service.py:1444-1549 `_sync_fills()`
    │        입력: broker.get_fills() → domain.models.FillEvent
    │
    └──▶ (broker_native_order_id 매칭) ──▶ broker_fill_snapshots  (KIS VTTC0081R 일별체결조회 백필)
             생성 경로: fill_history_sync.py `sync_fill_history_for_account()`
             독립적인 dedupe_key, order_request_id는 사후 조회로 채워짐(nullable)

position_snapshots  (계좌×종목, 브로커가 보고하는 시점별 quantity/average_price)
    생성 경로: 미확인(본 조사 범위 밖) — KIS 계좌 조회 폴링으로 채워지는 것으로 추정, source_of_truth ENUM('internal','broker','reconciled')이 이미 두 출처를 구분하도록 설계되어 있음
```

핵심 관찰 3가지:

1. **`fill_events`에는 `account_id`/`instrument_id`/`side`가 없다.** `broker_order_id → order_requests.instrument_id / order_requests.side`, `order_requests.account_id`로 join해야 한다([`0001_initial_schema.sql:288-346`](../../../db/migrations/0001_initial_schema.sql)). 이동평균 계산 엔진은 이 join을 매 fill마다 수행하거나, 인입 시점에 미리 비정규화(denormalize)해야 한다.
2. **`fill_events`와 `broker_fill_snapshots`는 서로 다른 테이블, 서로 다른 dedup 키를 갖는 독립 경로다.** `broker_fill_snapshots.order_request_id`는 [`0031_link_fill_snapshots_to_orders.sql`](../../../db/migrations/0031_link_fill_snapshots_to_orders.sql)에서 nullable FK로 추가되었을 뿐이며, 두 테이블이 같은 실제 체결을 항상 1:1로 가리킨다는 보장은 없다.
3. **`position_snapshots.average_price`는 브로커 원장값이다.** `source_of_truth` CHECK 제약(`'internal' | 'broker' | 'reconciled'`)이 이미 이 구분을 스키마 차원에서 인정하고 있다([`0001_initial_schema.sql:179-192`](../../../db/migrations/0001_initial_schema.sql)). 이번 설계로 추가하는 `position_cost_basis_state`(9절)는 `source_of_truth='internal'`에 대응하는 개념이며, 브로커 값을 대체하지 않는다.

### 2.1 미확인 경로 (구현 착수 전 확인 필요)

- **KIS websocket 체결 통보**: `fill_events.source_channel` CHECK 제약은 `'websocket' | 'rest_poll' | 'backfill' | 'manual'`을 허용하도록 이미 설계되어 있으나([`0001_initial_schema.sql:361`](../../../db/migrations/0001_initial_schema.sql)), 이번 조사에서 확인한 유일한 writer인 `_sync_fills()`는 항상 `source_channel="rest_poll"`을 사용한다. **websocket 경로로 fill_events가 채워지는 별도 writer가 존재하는지는 확인하지 못했다.** 존재한다면 순서·지연 특성이 다를 수 있으므로 5절의 정렬 키 설계에 영향을 줄 수 있다.
- **`position_snapshots` 생성 경로**: 이 문서는 `position_snapshots` 테이블의 존재와 컬럼만 확인했고, 실제로 어떤 서비스가 이를 채우는지는 조사 범위에 포함하지 않았다.
- **숏 포지션 가능성**: 국내주식 계좌에서 매도 후 음수 잔량이 실제로 발생하는지 미확인.
- **`admin_ui`의 실현 손익 소비 화면**: 어떤 컴포넌트가 `/performance-summary` 등을 소비하는지 미확인.

## 3. 이동평균법 실현 손익 계산 의미론

### 3.1 이동평균 vs FIFO (비교, 이번 설계는 이동평균 확정)

| | FIFO | 이동평균(이번 설계 확정) |
|---|---|---|
| 원가 추적 단위 | 매수 lot 개별 추적 | 계좌×종목 단일 평균값 |
| 매도 시 계산 | 가장 오래된 lot부터 순차 소진 | 그 시점의 평균단가 하나만 사용 |
| 저장 상태 크기 | O(미청산 lot 수) | O(1) — 종목당 1행 |
| 재계산(replay) 특성 | 특정 lot부터 재개 가능 | 반드시 계좌×종목 히스토리 전체를 처음부터 재생해야 함(4절 참고) |
| 세무 정확도 | 한국 세법상 통용되는 방식 중 하나 | 별도 세무 목적 계산이 필요하면 후속 확장(FIFO 병행)으로 분리 |

### 3.2 상태 전이 규칙

계좌×종목 단위 상태 `(quantity, average_cost)`를 유지하며, 정렬된 fill을 하나씩 순서대로 적용한다.

```
BUY 체결 적용:
    new_quantity = quantity + fill.quantity
    new_average_cost = (quantity * average_cost + fill.quantity * fill.price) / new_quantity
    realized_pnl_event 생성 없음

SELL 체결 적용:
    realized_pnl_gross = (fill.price - average_cost) * fill.quantity
    realized_pnl_net = realized_pnl_gross - fee - tax
    new_quantity = quantity - fill.quantity
    new_average_cost = average_cost                 # 매도는 평균단가를 바꾸지 않음
    if new_quantity == 0:
        new_average_cost = 0                         # 완전 청산 → 원가 리셋
    realized_pnl_event 1건 생성
```

- **완전 청산 후 원가 리셋**: `quantity == 0`이 되는 순간 `average_cost = 0`으로 리셋한다. 이후 재매수는 완전히 새로운 원가 계산으로 시작한다(직전 매도 손익과 무관).
- **같은 날 다회 매수/매도, 부분체결, 장중 재매수**: 별도 분기를 두지 않는다. 정렬된 fill을 순서대로 적용하는 것만으로 자동 처리된다 — 이것이 상태 전이 함수로 설계하는 핵심 이유다.
- **숏 포지션(2.1절 미확인 사항)**: `new_quantity < 0`이 되는 경우가 발생하면 계산을 계속 진행하지 않고 해당 계좌×종목을 "이상 상태"로 격리한다(8절). 조용히 음수 평균단가를 계산하지 않는다.

### 3.3 fee/tax 반영 정책 — 체결 건별 반영 확정

세 가지 후보를 비교한다.

| 방식 | 장점 | 단점 | 채택 여부 |
|---|---|---|---|
| 체결 건별 반영 | `fill_events.fill_fee`/`fill_tax`가 이미 존재, 배분 규칙 불필요 | 브로커가 fee/tax를 fill 단위로 정확히 내려주지 않으면 결측 발생 | **채택** |
| 주문 단위 배분 | fee/tax가 주문 단위로만 내려오는 경우 대응 가능 | 부분체결 시 수량 비례/균등 배분 중 임의 선택 필요 — 추가 불확실성 | 미채택 |
| 일단 제외 | 구현 단순 | 실현 손익을 과대평가 → 리스크 판단에 위험 | 미채택 |

`fill_fee`/`fill_tax`가 `None`인 경우 0으로 처리하되, 이를 "0으로 간주됨"으로 구분하기 위해 `realized_pnl_events.fee_tax_source`(`'reported' | 'assumed_zero'`)를 남긴다(9.2절).

## 4. 신규 엔티티 / 테이블 제안

세 층위로 분리한다: **가변 상태(cost basis)** / **불변 원장(realized PnL ledger)** / **파생 집계(daily aggregate)**. 여기에 실행 이력(computation run)과 장애 복구 큐(recompute queue)를 더한다.

```
trading.position_cost_basis_state       -- (account_id, instrument_id) 복합 PK, 가변
trading.realized_pnl_events             -- append-only, UNIQUE(fill_event_id)
trading.realized_pnl_daily_aggregates   -- (account_id, instrument_id, trade_date) 파생, 재생성 가능
trading.realized_pnl_computation_runs   -- 실시간 반영/백필 실행 이력 (fill_sync_runs와 동일 패턴)
trading.realized_pnl_recompute_queue    -- 장애 복구 큐 (8절)
```

### 4.1 `position_cost_basis_state`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `account_id` | UUID FK `accounts` | |
| `instrument_id` | UUID FK `instruments` | |
| `quantity` | NUMERIC(24,8) | 현재 이동평균 계산상 잔량 |
| `average_cost` | NUMERIC(20,8) | 현재 평균 매입단가 |
| `last_applied_fill_event_id` | UUID FK `fill_events`, nullable | 마지막으로 적용한 fill — idempotency 앵커 |
| `last_applied_fill_timestamp` | TIMESTAMPTZ, nullable | out-of-order 판단 기준(6절) |
| `recompute_required` | BOOLEAN DEFAULT FALSE | 8절 복구 계약 |
| `recompute_reason` | VARCHAR(64), nullable | |
| `updated_at` | TIMESTAMPTZ | |

PK: `(account_id, instrument_id)`.

### 4.2 `realized_pnl_events`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `realized_pnl_event_id` | UUID PK | |
| `account_id` | UUID FK `accounts` | |
| `instrument_id` | UUID FK `instruments` | |
| `fill_event_id` | UUID FK `fill_events`, **UNIQUE NOT NULL** | idempotency 1차 방어선 |
| `broker_order_id` | UUID FK `broker_orders` | |
| `order_request_id` | UUID FK `order_requests` | 조회 편의를 위한 비정규화 |
| `sell_quantity` | NUMERIC(24,8) | |
| `sell_price` | NUMERIC(20,8) | |
| `avg_cost_basis_before` | NUMERIC(20,8) | 계산에 사용된 평균단가 스냅샷 |
| `fee` | NUMERIC(20,8) | |
| `tax` | NUMERIC(20,8) | |
| `fee_tax_source` | VARCHAR(16) CHECK IN (`'reported'`,`'assumed_zero'`) | |
| `realized_pnl_gross` | NUMERIC(20,8) | `(sell_price - avg_cost_basis_before) * sell_quantity` |
| `realized_pnl_net` | NUMERIC(20,8) | `gross - fee - tax` |
| `position_quantity_after` | NUMERIC(24,8) | 이 이벤트 반영 후 잔량(0 = 완전 청산) |
| `computation_run_id` | UUID FK `realized_pnl_computation_runs` | |
| `superseded_by_event_id` | UUID FK `realized_pnl_events`, nullable, self-ref | 정정 시 무효화 마킹(7절) |
| `fill_timestamp` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |

**append-only 원칙**: 이 테이블은 UPDATE/DELETE하지 않는다. 정정이 필요하면 `superseded_by_event_id`를 채운 보정 행을 추가로 append한다(7.3절).

### 4.3 `realized_pnl_daily_aggregates`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `account_id` | UUID | |
| `instrument_id` | UUID | |
| `trade_date` | DATE | `fill_timestamp`를 KST로 변환한 날짜 (`fill_history_sync.py`의 `_KST` 상수와 동일 정책) |
| `realized_pnl_net_sum` | NUMERIC(20,8) | |
| `sell_event_count` | INTEGER | |
| `computation_run_id` | UUID | 마지막 갱신 run |
| `updated_at` | TIMESTAMPTZ | |

PK: `(account_id, instrument_id, trade_date)`. **이 테이블은 캐시다** — `realized_pnl_events`에서 언제든 `GROUP BY`로 재생성 가능해야 하며 그 자체가 진실의 원천이 되면 안 된다.

### 4.4 `realized_pnl_computation_runs`

`trading.fill_sync_runs`([`0029_add_fill_history_snapshot_tables.sql:1-26`](../../../db/migrations/0029_add_fill_history_snapshot_tables.sql))와 동일한 관측성 패턴을 따른다.

| 컬럼 | 설명 |
|---|---|
| `computation_run_id` PK | |
| `run_type` CHECK IN (`'realtime_incremental'`,`'backfill_replay'`) | |
| `account_id` nullable | null = 다계좌 배치 |
| `status` CHECK IN (`'running'`,`'completed'`,`'partial'`,`'failed'`) | |
| `fills_applied` / `fills_skipped_duplicate` / `fills_replayed` / `anomalies_detected` INTEGER | 8절 관측 지표 |
| `started_at` / `completed_at` | |
| `summary_json` | |

### 4.5 `realized_pnl_recompute_queue`

8절 복구 계약의 저장소.

| 컬럼 | 설명 |
|---|---|
| `recompute_queue_id` PK | |
| `account_id`, `instrument_id` | |
| `reason_code` CHECK IN (`'ledger_write_failed'`,`'out_of_order_fill_detected'`,`'anomaly_negative_quantity'`,`'manual_request'`) | |
| `triggering_fill_event_id` nullable | |
| `requested_at` | |
| `resolved_at` nullable | |
| `resolved_by_computation_run_id` nullable FK | |

## 5. 정렬 키(tie-break) 설계

이동평균 계산은 **순서에 강하게 의존**한다. 정렬 키를 다음 우선순위로 확정한다.

1. **`fill_timestamp`** (1차) — KIS 체결시각(초 단위). 동시각 다건 발생 가능.
2. **`broker_fill_id`** (2차, 있을 때) — KIS `CCLD_NUM`. **주의**: 이 값이 계좌 전체에서 전역적으로 단조 증가한다는 것은 KIS 문서로 확인하지 못했다. 같은 주문/같은 날 내에서는 순서를 신뢰할 수 있다는 가정만 채택하고, 이 가정 자체를 8절 관측 대상에 포함한다(가정이 깨지면 `anomaly_detected`로 표시).
3. **`fill_events.created_at`** (3차, 최종 사실상의 fallback) — 우리 DB가 그 fill을 실제로 저장한 시각(`DEFAULT NOW()`). **`fill_event_id`를 정렬 기준으로 쓰지 않는다** — `fill_event_id`는 `gen_random_uuid()` 기본값을 갖는 무작위 UUID이므로 수신 순서와 아무 관계가 없다. `created_at`은 우리 시스템이 실제로 그 행을 기록한 시각이므로 "수신 순서"에 대한 유일하게 신뢰 가능한 fallback이다.
4. **`fill_event_id`** (4차, 존재성만 보장하는 절대 최종 tie-break) — 위 세 키가 모두 완전히 동일한 극히 드문 경우에만, 정렬 순서에 아무 의미를 부여하지 않고 단지 "결정적인 순서 하나를 고정"하기 위한 용도로만 사용한다. 이 경우는 8절 `anomalies_detected`에 별도로 기록해 관측 가능하게 한다.

```sql
ORDER BY fill_timestamp ASC, broker_fill_id ASC NULLS LAST, created_at ASC, fill_event_id ASC
```

## 6. idempotency 및 replay 설계

- **1차 방어**: `fill_events` 자체의 dedup([`order_sync_service.py:1490-1529`](../../../src/agent_trading/services/order_sync_service.py) — `broker_fill_id` 우선, 없으면 `(broker_order_id, fill_timestamp, fill_price, fill_quantity)` 복합키). 이 로직은 재발명하지 않는다.
- **2차 방어**: `realized_pnl_events.fill_event_id` UNIQUE 제약. 같은 fill을 두 번 적용하려는 시도는 DB 제약 위반으로 즉시 차단된다.
- **replay가 필요한 이유**: 이동평균은 히스토리 의존적이다. 중간 지점에서 시작해 patch하듯 계산할 수 없다 — 특정 시점 이전의 fill이 새로 발견되면 그 시점 이후의 모든 `average_cost`/`realized_pnl_events`가 이미 틀린 값이다. 따라서 replay는 항상 **"이 계좌×종목의 전체 fill 히스토리를 정렬한 뒤 처음부터 다시 적용"**하는 방식이며, 부분 replay는 지원하지 않는다.
- **replay와 기존 이벤트의 관계**: replay를 실행하는 `computation_run`은 새 `realized_pnl_events` 행을 만들지 않고 기존 행을 재사용하되(같은 `fill_event_id`이므로 UNIQUE 제약이 재삽입을 막음), 계산 결과가 기존 저장값과 다르면 7.3절의 보정 이벤트로 처리한다.

## 7. out-of-order / duplicate / correction 처리

### 7.1 out-of-order 수신

실시간 반영 중, 해당 계좌×종목의 `position_cost_basis_state.last_applied_fill_timestamp`보다 **이전** 시각의 fill이 새로 도착하면:

1. 즉시 그 fill 하나만 patch하지 않는다(6절 이유).
2. `realized_pnl_recompute_queue`에 `reason_code='out_of_order_fill_detected'`로 등록한다.
3. 해당 계좌×종목의 상태를 `recompute_required=true`로 표시한다.
4. 별도 replay(`computation_run_id`)가 그 계좌×종목 전체를 재계산할 때까지, 조회 API는 "재계산 대기 중"임을 노출한다(9.3절).

### 7.2 중복 수신

5절/6절의 다층 방어로 처리된다. 중복이 감지되면 `computation_run.fills_skipped_duplicate`를 증가시키고 조용히 넘어간다(이것은 정상 동작이며 장애가 아니다).

### 7.3 정정(correction)

체결 자체가 취소되는 경우는 실무상 드물지만, 오수신 필드나 KIS 응답 정정은 발생할 수 있다. **UPDATE/DELETE를 사용하지 않는다.** 원본 `realized_pnl_event`에 `superseded_by_event_id`를 채우고, 올바른 값을 반영한 보정 행을 새로 append한다(음수 realized_pnl로 원본을 상쇄한 뒤 정정값을 다시 append하는 2단계 방식, 회계상의 취소선 방식과 동일). 이렇게 해야 "무엇이 언제 왜 바뀌었는지"가 원장에서 영구히 조회 가능하다.

## 8. 장애 시 복구 계약

**요구사항**: "fill 저장 성공 후 ledger 실패"를 조용히 허용하지 않는다.

- fill이 `fill_events`에 성공적으로 커밋된 뒤, ledger 갱신(cost basis 적용 + realized_pnl_event 생성)이 실패하면:
  1. fill 저장 자체는 롤백하지 않는다(체결 사실은 이미 발생한 사실이므로).
  2. 해당 계좌×종목을 `position_cost_basis_state.recompute_required=true`로 표시하거나, 해당 상태 행이 아직 없으면 `realized_pnl_recompute_queue`에 `reason_code='ledger_write_failed'`로 등록한다.
  3. 운영 지표로 관측 가능해야 한다 — `computation_run.anomalies_detected` 증가 및 로그 경고(수준: warning 이상, 조용히 성공으로 처리하지 않음).
- 이 계약은 [`AGENTS.md`](../../../AGENTS.md)의 "실패한 broker, KIS, DB 작업을 조용히 성공으로 변환하지 않는다"는 원칙과 [`no_bypass_policy.md`](../../80_harness_engineering/no_bypass_policy.md)의 관측 가능성 요구를 그대로 따른 것이다.
- 복구는 별도 배치(4절 `computation_run_id(run_type='backfill_replay')` 또는 대상 축소된 재계산 작업)가 `recompute_queue`/`recompute_required` 항목을 소진하는 방식으로 수행한다. 자동 즉시 재시도는 설계에 포함하지 않는다(이동평균의 순서 의존성상, 즉시 재시도가 또 다른 out-of-order 상황을 만들 수 있기 때문).

## 9. API / read model 설계

**"계산 엔진"과 "조회 API"를 분리한다.** 조회 API는 ledger를 읽기만 하고 계산하지 않는다(이 절은 설계 방향만 제시하며, 구체적인 엔드포인트 구현은 [`kis_realized_pnl_moving_average_action_plan.md`](../../40_action_plans/kis_realized_pnl_moving_average_action_plan.md) 5단계에서 다룬다).

### 9.1 노출 단위 분리

| 단위 | 소스 | 비고 |
|---|---|---|
| 체결 단위 | `realized_pnl_events` 행 자체 | 가장 세밀한 감사 단위 |
| 일자 단위 | `realized_pnl_daily_aggregates` | 파생, 재생성 가능 |
| 종목 누계 | `realized_pnl_events` `GROUP BY instrument_id` | 별도 테이블 생성하지 않음(과도한 사전 설계 방지) |
| 주문 단위 | `realized_pnl_events` `GROUP BY order_request_id` | 별도 테이블 생성하지 않음 |

### 9.2 "브로커 원장값"과 "우리 내부 계산값" 대사(reconciliation)

- `position_snapshots.average_price`(브로커 원장, `source_of_truth='broker'`)와 `position_cost_basis_state.average_cost`(우리 계산, 내부)는 **다른 목적의 값이며 항상 같을 필요는 없다**(브로커는 세금/수수료 처리 방식이 다를 수 있음).
- 대사 리포트는 두 값의 차이를 "오류"로 자동 판정하지 않고 **관측 가능한 차이(diff, 이 문서에서는 "전후 차이"로 표기)**로만 노출한다. 임계값 초과 시에만 운영 알림을 고려한다(구체 임계값은 후속 확장에서 결정).

### 9.3 재계산 대기 상태의 노출

`position_cost_basis_state.recompute_required=true`인 계좌×종목은 조회 API 응답에 `stale: true` 또는 동등한 플래그로 노출해, 소비자가 "이 숫자는 아직 확정되지 않았다"를 알 수 있게 한다.

## 10. 운영 대사 설계

`fill_events`(1차 입력)와 `broker_fill_snapshots`(KIS VTTC0081R 백필)는 서로 다른 dedup 키를 갖는 독립 경로다. 대사 리포트는 다음을 계좌×일자 단위로 비교한다.

- `fill_events`에서 파생한 `(symbol, side, filled_quantity, fill_price)` 합계
- `broker_fill_snapshots`에서 파생한 동일 구조의 합계

차이가 발생하면 "누락된 실시간 체결"과 "이중 관측"을 구분해 표시해야 한다. 이 리포트는 ledger 계산에 개입하지 않는 **읽기 전용 관측 기능**으로 한정한다 — `broker_fill_snapshots`를 ledger의 입력으로 승격하는 것은 이번 설계 범위가 아니다.

## 11. 기존 `performance_summary` 및 UI/API 하위호환 방안

- `AccountPerformanceSummary.realized_pnl`(현금흐름 근사)과 신규 ledger 기반 realized PnL은 **당분간 병행 노출**한다. 기존 필드명·의미를 변경하지 않고, 신규 지표는 별도 필드/엔드포인트로 추가한다.
- `paper_performance_metrics.md`의 "per-order 기준" 서술은 사실 그대로 유지하되, 신규 ledger 지표가 도입되면 "다음 절 참고"로 상호 참조를 추가한다(구현 단계에서 처리, 이번 설계 문서에서는 갱신하지 않음).
- `winning_trade_count`/`losing_trade_count`/`profit_factor` 등 기존 필드를 소비하는 화면/게이트(`GateEvaluationService` 등)는 이번 설계로 즉시 변경되지 않는다. 교체 여부와 시점은 [`kis_realized_pnl_moving_average_action_plan.md`](../../40_action_plans/kis_realized_pnl_moving_average_action_plan.md) 6단계에서 별도로 결정한다.
- 리스크 게이트, sell guard(`sell_guard.py`), 주문 제출 의미론은 이 설계로 변경하지 않는다.

## 12. 향후 확장 범위

- 과거 체결 백필(전체 replay) 및 실행 결과 검증 절차.
- 종목별 누계/체결별/일자별 조회 API 구현.
- admin_ui 노출 화면.
- `broker_fill_snapshots`와의 정식 대사 리포트 및 임계값 정책.
- FIFO 병행 지원(세무 목적 필요 시 별도 lot 테이블 추가).
- 숏 포지션 지원 여부 검토(현재는 발생 시 격리만 설계, 지원 자체는 범위 밖).
- KIS websocket 체결 통보 경로 확인 후, 필요 시 5절 정렬 키 설계 재검토.
