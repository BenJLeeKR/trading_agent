# 12. KIS 실체결 기준 이동평균 실현 손익(Realized PnL) Ledger — 상세 설계

> **문서 상태**: 설계 + 일부 구현 완료 상태다.
> - 4절의 신규 테이블 5종은 `db/migrations/0053_add_realized_pnl_ledger_tables.sql` + `0054_add_realized_pnl_support_indexes.sql`로 migration 초안이 작성되었지만 **아직 어떤 DB에도 실행되지 않았다.**
> - entity/repository 계층(4절)은 구현 완료([`domain/entities.py`](../../../src/agent_trading/domain/entities.py), [`repositories/contracts.py`](../../../src/agent_trading/repositories/contracts.py) 등).
> - **계산 엔진(3.2절)은 순수 함수로 구현 완료** — [`src/agent_trading/services/realized_pnl_engine.py`](../../../src/agent_trading/services/realized_pnl_engine.py) (`apply_fill_to_cost_basis()`, `replay_fills()`). 단위 테스트는 [`tests/services/test_realized_pnl_engine.py`](../../../tests/services/test_realized_pnl_engine.py).
> - **repository write orchestration(8절)도 구현 완료** — [`src/agent_trading/services/realized_pnl_ledger_service.py`](../../../src/agent_trading/services/realized_pnl_ledger_service.py)의 `RealizedPnlLedgerService.apply_fill()`. `fill_events` → `NormalizedFill` 정규화(join 포함), state 조회, 계산 엔진 호출, state/event/일자집계 저장, idempotency, out-of-order·실패 시 recompute_queue/recompute_required 처리까지 담당한다. 단위 테스트는 [`tests/services/test_realized_pnl_ledger_service.py`](../../../tests/services/test_realized_pnl_ledger_service.py).
> - **runtime ingestion 훅 연결도 구현 완료** — [`order_sync_service.py`](../../../src/agent_trading/services/order_sync_service.py)의 `_sync_fills()`가 REST 기반(`get_fills()`) 신규 fill을 `fill_events`에 저장한 **직후**(dedup을 통과한 fill에만) `RealizedPnlLedgerService.apply_fill()`을 호출한다. 훅 실패는 fill 저장 성공과 분리되어 로그(`applied`/`skipped_duplicate`/`recompute_required`/`failed` 집계)로 관측 가능하다. 단위 테스트는 `tests/services/test_order_sync_service.py`의 `TestRealizedPnlLedgerHook`.
> - **recompute/replay 복구 경로도 구현 완료** — [`src/agent_trading/services/realized_pnl_recompute_service.py`](../../../src/agent_trading/services/realized_pnl_recompute_service.py)의 `RealizedPnlRecomputeService`. `recompute_account_instrument()`가 계좌×종목의 전체 fill 히스토리를 5절 tie-break로 정렬해 `replay_fills()`로 처음부터 재계산하고, `realized_pnl_events`/`realized_pnl_daily_aggregates`를 upsert로 authoritative하게 다시 쓴 뒤 `recompute_required`를 해제하고 관련 `recompute_queue` 항목을 resolve한다. `process_pending_queue()`는 pending 항목을 계좌×종목 단위로 coalesce해 이 메서드를 반복 호출하는 배치 진입점이다. 단위 테스트는 [`tests/services/test_realized_pnl_recompute_service.py`](../../../tests/services/test_realized_pnl_recompute_service.py). **정정 방식이 당초 설계(7.3절 "supersede 행 append")에서 실제 구현 중에 변경됐다** — 아래 7.3절 갱신 참고.
> - **`process_pending_queue()`를 실제 운영 경로에 연결 완료** — [`scripts/run_realized_pnl_recompute_worker.py`](../../../scripts/run_realized_pnl_recompute_worker.py)가 `RealizedPnlRecomputeService.process_pending_queue()`를 그대로 호출하는 독립 장기 실행 워커다(`reconciliation-worker`와 동일한 "long-lived worker가 자체 polling 루프로 pending 큐를 소비" 패턴, `run_ops_scheduler.py`의 거래시간대 종속 subprocess-cadence 패턴과는 별개). `docker-compose.yml`에 `realized-pnl-recompute-worker` 서비스로 배포된다(기본 interval 300초, 큐 limit 100 — `REALIZED_PNL_RECOMPUTE_WORKER_INTERVAL_SECONDS`/`REALIZED_PNL_RECOMPUTE_WORKER_QUEUE_LIMIT`로 조정 가능). 계좌×종목 단위 실패는 서비스 자체가 흡수해 워커 전체를 중단시키지 않으며, 사이클마다 `recompute_processed_count`/`recompute_completed_count`/`recompute_failed_count`/`recompute_queue_resolved_count`를 로그로 남긴다. 이 recompute 계산/replay 로직 자체는 이번 연결 작업에서 전혀 수정하지 않았다.
> - **read-only Inspection API도 구현 완료** — [`src/agent_trading/api/routes/realized_pnl.py`](../../../src/agent_trading/api/routes/realized_pnl.py)에 5개 endpoint를 추가했다: `GET /performance/realized-pnl/positions`(계좌×종목 종목 누계 + 현재 상태, `instrument_id` 생략 시 계좌 전체), `GET /performance/realized-pnl/events`(체결별 event 목록), `GET /performance/realized-pnl/daily`(일자별 aggregate 목록), `GET /performance/realized-pnl/recompute-queue`(미해결 recompute 큐 항목), `GET /performance/realized-pnl/summary`(계좌 전체 또는 단일 종목 기간 요약 — 아래 참고). 전부 **계산 없이 저장된 값만 읽는다** — 계산은 여전히 `realized_pnl_engine.py`/`realized_pnl_ledger_service.py`/`realized_pnl_recompute_service.py`에 전속돼 있다. authoritative source: 체결 상세=`realized_pnl_events`, 일자 요약=`realized_pnl_daily_aggregates`, 종목 누계(`realized_pnl_net_cumulative`)=해당 계좌×종목의 `realized_pnl_daily_aggregates` 전체를 단순 합산(재계산 아님). `positions` endpoint가 `instrument_id` 없이 계좌 전체를 나열할 수 있도록 `PositionCostBasisStateRepository.list_by_account()`를 최소 범위로 추가했다(신규 migration 없음, 기존 테이블 조회 메서드 추가뿐). 단위 테스트는 `tests/api/test_inspection.py`의 `TestRealizedPnl`.
> - **summary endpoint(Admin UI N+1 제거용)도 구현 완료** — `GET /performance/realized-pnl/summary`(`account_id`+`start_date`+`end_date` 필수, `instrument_id` 선택). `RealizedPnlDailyAggregateRepository.list_by_account()`를 최소 추가해(신규 migration 없음) 계좌의 모든 종목의 일자 집계를 **단일 조회**로 가져온 뒤 종목별/전체로 단순 합산한다 — Admin UI가 종목 "전체" 조회 시 종목마다 `daily`를 반복 호출하던 N+1을 없애기 위한 endpoint다. `recompute_required`는 `PositionCostBasisStateRepository`의 기존 `get()`/`list_by_account()`를 그대로 쓴다(추가 확장 없음). 단위 테스트는 `tests/api/test_inspection.py`의 `TestRealizedPnl`(summary 관련 4건). **Admin UI 전환 완료** — `RealizedPnlView.tsx`가 요약 카드/종목별 탭/recompute 배지를 `summary` 단일 호출로 채운다(계좌 전체·단일 종목 공통). `positions`는 여전히 종목 후보 드롭다운(all-time)용으로만 남았고, 탭 A(일자별)는 `summary`가 날짜별 분해를 제공하지 않아 `daily` N+1을 그대로 쓴다 — 종목 "전체" N+1은 요약/종목별 탭에서는 제거됐고 탭 A에만 남는다.
> - **탭 A(일자별) N+1 제거용 `daily-summary` endpoint도 백엔드 구현 완료** — `GET /performance/realized-pnl/daily-summary`(`account_id`+`start_date`+`end_date` 필수, `instrument_id` 없음). `summary`가 이미 추가한 `RealizedPnlDailyAggregateRepository.list_by_account()`를 그대로 재사용해(신규 repository 메서드·migration 없음) 계좌의 모든 종목 일자 집계를 단일 조회로 가져온 뒤 **날짜별로** 단순 합산한다(`summary`는 종목별로 합산 — 역할 분리). 기존 `daily`/`summary`/`events`/`positions`/`recompute-queue` 계약은 바꾸지 않았다. 단위 테스트는 `tests/api/test_inspection.py`의 `TestRealizedPnl`(daily-summary 관련 4건). **Admin UI 탭 A 전환도 구현 완료** — `RealizedPnlView.tsx`의 탭 A는 종목 "전체"일 때 `daily-summary` 단일 호출로, 단일 종목 선택 시에는 여전히 기존 `daily`로 채운다. 종목 "전체"의 탭 A `daily` fan-out(N+1)은 제거됐다 — 실현손익 화면 전체(요약/종목별/일자별)에서 종목 전체 N+1이 모두 사라졌다.
> - **Admin UI 선행 백엔드 확장(daily aggregate 매수금액/매도금액/비용 합계)도 구현 완료** — `design/realized_pnl_screen_spec.md`의 P0-선행 항목. `db/migrations/0055_add_realized_pnl_daily_aggregate_amount_sums.sql`로 `realized_pnl_daily_aggregates`에 `buy_amount_sum`/`sell_amount_sum`/`fee_tax_sum`을 추가하고, `RealizedPnlLedgerService._update_daily_aggregate()`(실시간 증분 반영)와 `RealizedPnlRecomputeService._rebuild_daily_aggregates()`(절대값 재구성)가 함께 채운다. `GET /performance/realized-pnl/daily` 응답에도 그대로 노출된다. 상세는 4.3절.
> - **Admin UI 실현손익 화면(P0)도 구현 완료** — `admin_ui/src/components/RealizedPnlView.tsx`, `design/realized_pnl_screen_spec.md` P0 항목. 현재는 `positions`+`daily` N+1 경로를 쓰며, 위 신규 `summary` endpoint로의 전환은 아직 하지 않았다(후속).
> - **아직 연결되지 않음**: 대규모 backfill CLI(수천 계좌×종목 순회), Admin UI를 `summary` endpoint로 전환.
> - **idempotency 현재 보장 범위**: SELL은 `realized_pnl_events.fill_event_id` UNIQUE 조회로 완전히 감지된다. BUY는 `position_cost_basis_state.last_applied_fill_event_id`와의 일치만 확인하므로 "가장 최근에 적용된 fill과 정확히 같은 재적용"만 막는다 — 그보다 이전 BUY fill의 non-adjacent 중복 재적용은 실시간 반영 경로(`RealizedPnlLedgerService.apply_fill`)에서는 여전히 막히지 않는다. **다만 recompute/replay 경로는 이 한계를 물려받지 않는다** — replay는 반복 호출이 아니라 `fill_events` 테이블의 distinct 행을 정렬해 정확히 한 번씩만 훑으므로, 과거 incremental 반영이 실수로 잘못 누적했더라도 replay는 그 잘못된 상태를 신뢰하지 않고 원본 fill부터 다시 계산해 사실상의 안전망이 된다(자세한 설명은 `realized_pnl_recompute_service.py` 모듈 docstring).
>
> - **`fee_tax_source` 4값 확장 설계도 별도 검토 턴에서 계약까지 확정됐다(구현 미착수)** — `reported`/`assumed_zero` 2값을 `calculated_from_policy`/`policy_not_applicable`를 더한 4값 체계로 확장하는 결정, `VARCHAR(16)→VARCHAR(32)` migration 방향, 집계 API `provenance_breakdown` 최소 계약을 13절에 canonical하게 기록했다. 아직 코드/migration은 전혀 바뀌지 않았다 — 13절이 다음 구현 turn의 기준 문서다.
>
> - **매수(BUY) 수수료 pool 배분(C안 확장형)도 설계+구현 완료** — `average_cost`는 절대 바꾸지 않고, 매수 수수료를 `position_cost_basis_state.remaining_buy_fee_pool`에 별도로 누적했다가 SELL 시점에 보유수량 대비 매도수량 비율로 배분해 `realized_pnl_net = gross - fee - tax - allocated_buy_fee`로 반영한다. `db/migrations/0059_add_buy_fee_pool_allocation.sql`. 상세는 14절.
>
> 구현 순서와 단계 분리는 [`kis_realized_pnl_moving_average_action_plan.md`](../../40_action_plans/kis_realized_pnl_moving_average_action_plan.md)를 따른다.
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

### 2.1 현재 확인된 입력 경로와 아직 확인되지 않은 것

**현재 확인된 fill 입력 경로**는 REST 기반 `_sync_fills()`(`broker.get_fills()`) 하나뿐이다([`order_sync_service.py:1444-1549`](../../../src/agent_trading/services/order_sync_service.py)). 이 writer는 항상 `source_channel="rest_poll"`로 저장한다. `broker_fill_snapshots`는 KIS VTTC0081R(일별체결조회) 기반 백필/대사 전용 경로이며(1절), ledger의 1차 입력으로 쓰지 않는다(10절). **따라서 이 설계와 1차 구현(action plan 1~3단계)은 REST 기반 fill 입력만을 전제로 한다.**

이 전제 위에서, 아래는 구현 착수 전 확인이 필요한 항목이다.

- **websocket fill writer 존재 여부**: `fill_events.source_channel` CHECK 제약은 `'websocket' | 'rest_poll' | 'backfill' | 'manual'`을 허용하도록 이미 설계되어 있으나([`0001_initial_schema.sql:361`](../../../db/migrations/0001_initial_schema.sql)), 이번 조사에서 확인한 유일한 writer는 위의 REST 경로뿐이다. `'websocket'` 값은 스키마상 허용되어 있을 뿐, 그 값을 실제로 쓰는 별도 writer가 존재하는지는 확인하지 못했다. 존재한다면 순서·지연 특성이 다를 수 있으므로 5절의 정렬 키 설계에 영향을 줄 수 있다 — 확인되기 전까지는 REST 경로만 있다고 가정하고 설계한다.
- **`position_snapshots` 생성 경로**: 이 문서는 `position_snapshots` 테이블의 존재와 컬럼만 확인했고, 실제로 어떤 서비스가 이를 채우는지는 조사 범위에 포함하지 않았다.
- **숏 포지션 가능성**: 국내주식 계좌에서 매도 후 음수 잔량이 실제로 발생하는지 미확인. 6절/9절에서는 이를 "지원 여부가 결정되지 않은 것"으로 다루고, 임시로 DB 레벨 가드만 둔다.
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
- **숏 포지션(2.1절 미확인 사항)**: `new_quantity < 0`이 되는 경우(직전 상태 없이 SELL이 오거나, 보유 수량을 초과하는 SELL)는 계산을 계속 진행하지 않고 **엔진 레벨에서 예외로 명시 실패**한다(`MissingCostBasisStateError`/`InsufficientPositionQuantityError`, `realized_pnl_engine.py`). 그 예외를 잡아 `realized_pnl_recompute_queue`에 기록해 "이상 상태"로 격리하는 것은 8절에서 설명하는 **orchestration 레벨의 책임**이며, 아직 구현되지 않았다(다음 단계 — `order_sync_service` 연결).

> **구현 상태**: 위 상태 전이 규칙은 [`apply_fill_to_cost_basis()`](../../../src/agent_trading/services/realized_pnl_engine.py)로 그대로 구현되어 있다. 여러 fill을 순서대로 반영하는 replay는 [`replay_fills()`](../../../src/agent_trading/services/realized_pnl_engine.py)가 담당하며, `fill_timestamp` 역행만 감지해 `FillsNotSortedError`로 실패한다(그 이상의 out-of-order 복구는 7절대로 아직 범위 밖). 두 함수 모두 저장소를 호출하지 않는 순수 함수다 — 저장은 다음 단계의 책임이다.

### 3.3 fee/tax 반영 정책 — 체결 건별 반영 확정

세 가지 후보를 비교한다.

| 방식 | 장점 | 단점 | 채택 여부 |
|---|---|---|---|
| 체결 건별 반영 | `fill_events.fill_fee`/`fill_tax`가 이미 존재, 배분 규칙 불필요 | 브로커가 fee/tax를 fill 단위로 정확히 내려주지 않으면 결측 발생 | **채택** |
| 주문 단위 배분 | fee/tax가 주문 단위로만 내려오는 경우 대응 가능 | 부분체결 시 수량 비례/균등 배분 중 임의 선택 필요 — 추가 불확실성 | 미채택 |
| 일단 제외 | 구현 단순 | 실현 손익을 과대평가 → 리스크 판단에 위험 | 미채택 |

`fill_fee`/`fill_tax`가 `None`인 경우 0으로 처리하되, 이를 "0으로 간주됨"으로 구분하기 위해 `realized_pnl_events.fee_tax_source`(`'reported' | 'assumed_zero'`)를 남긴다(9.2절). 계산 엔진은 `fee_tax_source='assumed_zero'`인데 fee/tax가 0이 아닌 입력을 모순으로 보고 `FeeTaxSourceMismatchError`로 명시 실패한다(상류 정규화 단계의 버그를 조용히 넘기지 않기 위함).

**v1 범위의 알려진 단순화**: BUY 체결의 fee는 현재 평균단가 계산에 포함하지 않는다(3.2절 BUY 공식에 fee 항이 없음). 표준 원가회계에서는 매입 수수료를 원가에 포함하는 것이 더 정확하지만, 이번 v1은 설계 문서/실행 계획에 명시된 공식을 그대로 구현했다. 매입 수수료가 유의미한 규모라면 실현 손익이 실제 경제적 이익보다 소폭 과대평가될 수 있다 — 후속 확장 후보(12절)로 남긴다.

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
| `superseded_by_event_id` | UUID FK `realized_pnl_events`, nullable, self-ref | 예약 필드 — recompute/replay 경로는 upsert로 정정하므로 이 필드를 채우지 않는다(7.3절 갱신 참고). 현재 어떤 writer도 이 필드를 채우지 않는다 |
| `fill_timestamp` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |

**append-only 원칙(실시간 반영 경로 기준)**: `RealizedPnlLedgerService.apply_fill()`은 이 테이블에 `add()`만 쓴다 — 같은 fill을 두 번 다른 행으로 기록하지 않는다. 정정(out-of-order 등으로 계산값이 틀린 경우)은 recompute/replay 경로가 같은 identity(`realized_pnl_event_id`, `fill_event_id`로부터 결정론적으로 파생)를 유지한 `upsert()`로 계산값만 다시 쓴다 — `superseded_by_event_id`를 채운 별도 보정 행을 추가하는 방식은 `fill_event_id` UNIQUE 제약과 충돌해 채택하지 않았다. 자세한 내용은 7.3절.

### 4.3 `realized_pnl_daily_aggregates`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `account_id` | UUID | |
| `instrument_id` | UUID | |
| `trade_date` | DATE | `fill_timestamp`를 KST로 변환한 날짜 (`fill_history_sync.py`의 `_KST` 상수와 동일 정책) |
| `realized_pnl_net_sum` | NUMERIC(20,8) | |
| `sell_event_count` | INTEGER | |
| `buy_amount_sum` | NUMERIC(20,8) | `db/migrations/0055_add_realized_pnl_daily_aggregate_amount_sums.sql`. `Σ(sell_quantity × avg_cost_basis_before)` — Admin UI 실현손익 화면(`design/realized_pnl_screen_spec.md`)용 파생 합계 캐시, 새 손익 계산식이 아니다. |
| `sell_amount_sum` | NUMERIC(20,8) | 같은 migration. `Σ(sell_quantity × sell_price)`. |
| `fee_tax_sum` | NUMERIC(20,8) | 같은 migration. `Σ(fee + tax)`. |
| `computation_run_id` | UUID | 마지막 갱신 run |
| `updated_at` | TIMESTAMPTZ | |

PK: `(account_id, instrument_id, trade_date)`. **이 테이블은 캐시다** — `realized_pnl_events`에서 언제든 `GROUP BY`로 재생성 가능해야 하며 그 자체가 진실의 원천이 되면 안 된다. `buy_amount_sum`/`sell_amount_sum`/`fee_tax_sum`도 동일하다 — `realized_pnl_events`의 기존 필드를 합산한 것뿐이며, 이 세 컬럼을 기준으로 실현손익을 다시 계산하는 로직은 어디에도 없다(계산 엔진은 여전히 `realized_pnl_engine.py`에만 있다). 이 컬럼들은 3개 모두 NOT NULL DEFAULT 0로 추가됐으며, 0055 migration 실행 시점 이전에 쌓인 과거 행은 recompute(`RealizedPnlRecomputeService.recompute_account_instrument()`)를 거치기 전까지 0으로 남는다 — 신규 fill은 실시간 반영 경로가 즉시 채운다.

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

### 4.6 애플리케이션 타입 계층 — enum으로 승격한 필드와 str로 유지한 필드

DB 컬럼은 모두 `VARCHAR` + `CHECK` 제약이며 이번 단계에서 바꾸지 않는다. 다만
계산 엔진(다음 단계)이 분기 조건으로 직접 사용할 필드는 Python
`class X(str, Enum)`으로 승격해 오탈자·미정의 값 유입을 타입 체크 단계에서
막는다(`src/agent_trading/domain/enums.py`).

- **enum으로 승격**: `run_type` → `RealizedPnlComputationRunType`(값 2개,
  계산 엔진이 "단일 fill 증분 반영"과 "계좌×종목 전체 replay"를 분기하는
  기준이라 계산 엔진이 이 값에 직접 의존한다), `fee_tax_source` →
  `RealizedPnlFeeTaxSource`(값 2개, 계산 엔진이 매 이벤트 생성 시 반드시
  채우는 provenance 필드).
- **str로 유지**: `status`(`realized_pnl_computation_runs`)는
  `fill_sync_runs`/`snapshot_sync_runs`/`reconciliation_runs`의 실행 상태
  필드가 모두 str인 기존 관례를 따른다. `reason_code`
  (`realized_pnl_recompute_queue`)는 `PipelineStopReason`처럼 운영 경험에
  따라 값이 늘어날 수 있는 reason 계열 필드이므로, `status_reason_code`/
  `stop_reason` 등 기존 엔티티의 동일 계열 필드와 같이 str로 유지한다.

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
- **2차 방어(SELL)**: `realized_pnl_events.fill_event_id` UNIQUE 제약 + `RealizedPnlLedgerService.apply_fill()`의 사전 조회(`get_by_fill_event_id()`). 같은 SELL fill을 두 번 적용하려는 시도는 언제 재적용되든 정확히 감지·차단된다.
- **2차 방어(BUY, 현재 한계)**: BUY는 `realized_pnl_events` 행이 생기지 않아 같은 방식의 전역 dedup 앵커가 없다. 현재 구현은 `position_cost_basis_state.last_applied_fill_event_id`와의 일치만 확인한다 — "가장 최근에 적용된 fill과 정확히 같은 재적용"만 막고, 그보다 이전 BUY fill의 non-adjacent 재적용은 막지 못한다. 완전한 방지에는 fill 단위 적용 이력(별도 apply-log 또는 적용된 fill_event_id 집합)이 필요하며, 스키마 변경을 늘리지 않기 위해 이번 단계에서는 추가하지 않았다.
- **replay가 필요한 이유**: 이동평균은 히스토리 의존적이다. 중간 지점에서 시작해 patch하듯 계산할 수 없다 — 특정 시점 이전의 fill이 새로 발견되면 그 시점 이후의 모든 `average_cost`/`realized_pnl_events`가 이미 틀린 값이다. 따라서 replay는 항상 **"이 계좌×종목의 전체 fill 히스토리를 정렬한 뒤 처음부터 다시 적용"**하는 방식이며, 부분 replay는 지원하지 않는다.
- **replay와 기존 이벤트의 관계**: replay를 실행하는 `computation_run`은 새 `realized_pnl_events` 행을 만들지 않고 기존 행을 재사용하되(같은 `fill_event_id`이므로 UNIQUE 제약이 재삽입을 막음), 계산 결과가 기존 저장값과 다르면 7.3절의 보정 이벤트로 처리한다.

## 7. out-of-order / duplicate / correction 처리

### 7.1 out-of-order 수신

실시간 반영 중, 해당 계좌×종목의 `position_cost_basis_state.last_applied_fill_timestamp`보다 **이전** 시각의 fill이 새로 도착하면:

1. 즉시 그 fill 하나만 patch하지 않는다(6절 이유).
2. `realized_pnl_recompute_queue`에 `reason_code='out_of_order_fill_detected'`로 등록한다.
3. 해당 계좌×종목의 상태를 `recompute_required=true`로 표시한다.
4. 별도 replay(`computation_run_id`)가 그 계좌×종목 전체를 재계산할 때까지, 조회 API는 "재계산 대기 중"임을 노출한다(9.3절).

> **구현 상태**: 위 1~3단계는 [`RealizedPnlLedgerService.apply_fill()`](../../../src/agent_trading/services/realized_pnl_ledger_service.py)로 구현되어 있다(엔진을 호출하지 않고 즉시 recompute_queue + recompute_required로 우회). 4단계(별도 replay가 실제로 재계산을 완료하는 것)와 9.3절의 조회 API 노출은 아직 구현되지 않았다 — 지금은 상태가 `recompute_required=true`로 표시된 채 남아 있을 뿐 자동으로 해소되지 않는다.

### 7.2 중복 수신

5절/6절의 다층 방어로 처리된다. 중복이 감지되면 `computation_run.fills_skipped_duplicate`를 증가시키고 조용히 넘어간다(이것은 정상 동작이며 장애가 아니다).

### 7.3 정정(correction) — **[갱신] 실제 구현에서 확인된 제약으로 방식이 바뀜**

> 이 절은 당초 "superseded_by_event_id를 채운 보정 행 append" 방식으로 설계됐으나, recompute/replay 서비스를 실제로 구현하는 과정에서 그 방식이 `realized_pnl_events.fill_event_id` UNIQUE 제약과 근본적으로 충돌한다는 것이 확인됐다(같은 fill_event_id로 두 번째 행을 append할 수 없다). 아래는 실제 구현된 방식이다.

체결 자체가 취소되는 경우는 실무상 드물지만, out-of-order로 뒤늦게 도착한 fill 때문에 그 이후 모든 `realized_pnl_event`의 계산값이 이미 틀린 경우는 실제로 발생한다(7.1절). **정정은 UPDATE/DELETE 대신, 같은 fill의 identity를 유지한 upsert로 이루어진다.** `realized_pnl_event_id`가 `fill_event_id`로부터 결정론적으로 파생되므로(6절), recompute가 같은 fill을 다시 계산해도 항상 같은 `realized_pnl_event_id`가 나온다 — 이 identity를 그대로 유지한 채 계산값(`sell_quantity`/`sell_price`/`avg_cost_basis_before`/`fee`/`tax`/`realized_pnl_gross`/`realized_pnl_net`/`position_quantity_after`/`computation_run_id`)만 다시 쓴다(`RealizedPnlEventRepository.upsert()`, `INSERT ... ON CONFLICT (fill_event_id) DO UPDATE`). `created_at`은 최초 생성 시각으로 보존된다.

**"append-only"의 의미가 재정의됐다**: 이 저장소는 "같은 fill을 두 번 다른 행으로 기록하지 않는다"(fill_event_id당 정확히 1행)는 뜻으로 유지되지만, "그 1행의 계산값을 절대 다시 쓰지 않는다"는 뜻은 아니다. 실시간 반영 경로(`RealizedPnlLedgerService.apply_fill`)는 여전히 `add()`만 사용해 append-only를 지킨다 — 값을 다시 쓰는 upsert는 recompute/replay 경로만 쓴다. `superseded_by_event_id` 필드는 이 recompute 경로에서는 사용하지 않는다(값을 그 자리에서 바로 고치므로 "다른 행이 원본을 대체한다"는 개념 자체가 필요 없다) — 다만 필드 자체는 남겨 두어, 향후 운영자가 수동으로 별도 identity의 정정 행을 넣어야 하는 경우(예: 계산 로직 밖의 순수 데이터 오류)를 위해 예약해 둔다.

"무엇이 언제 왜 바뀌었는지"의 추적은 `realized_pnl_events` 행 자체가 아니라 `realized_pnl_computation_runs`(어떤 run이 이 값을 마지막으로 썼는지, `computation_run_id`로 역추적 가능)와 애플리케이션 로그로 남긴다 — 개별 이벤트 행의 "이전 값"은 보존되지 않는다는 뜻이며, 이는 당초 설계보다 감사 추적성이 약화된 지점이다(알려진 트레이드오프).

## 8. 장애 시 복구 계약

**요구사항**: "fill 저장 성공 후 ledger 실패"를 조용히 허용하지 않는다.

- fill이 `fill_events`에 성공적으로 커밋된 뒤, ledger 갱신(cost basis 적용 + realized_pnl_event 생성)이 실패하면:
  1. fill 저장 자체는 롤백하지 않는다(체결 사실은 이미 발생한 사실이므로).
  2. 해당 계좌×종목을 `position_cost_basis_state.recompute_required=true`로 표시하거나, 해당 상태 행이 아직 없으면 `realized_pnl_recompute_queue`에 `reason_code='ledger_write_failed'`로 등록한다.
  3. 운영 지표로 관측 가능해야 한다 — `computation_run.anomalies_detected` 증가 및 로그 경고(수준: warning 이상, 조용히 성공으로 처리하지 않음).
- 이 계약은 [`AGENTS.md`](../../../AGENTS.md)의 "실패한 broker, KIS, DB 작업을 조용히 성공으로 변환하지 않는다"는 원칙과 [`no_bypass_policy.md`](../../80_harness_engineering/no_bypass_policy.md)의 관측 가능성 요구를 그대로 따른 것이다.
- 복구는 별도 배치(4절 `computation_run_id(run_type='backfill_replay')` 또는 대상 축소된 재계산 작업)가 `recompute_queue`/`recompute_required` 항목을 소진하는 방식으로 수행한다. 자동 즉시 재시도는 설계에 포함하지 않는다(이동평균의 순서 의존성상, 즉시 재시도가 또 다른 out-of-order 상황을 만들 수 있기 때문).

> **구현 상태**: `RealizedPnlLedgerService.apply_fill()`이 위 계약을 구현했다 — 계산 엔진 예외와 repository 쓰기 실패(state upsert, event append, 일자 집계 갱신 중 발생하는 예외 포함) 모두 `realized_pnl_recompute_queue` 등록(`reason_code='ledger_write_failed'`) + `position_cost_basis_state.recompute_required=true` + `computation_run.anomalies_detected` 증가로 이어진다. 단, `broker_order`/`order_request` join 자체가 끊어진 경우(fill의 계좌/종목을 확정할 수 없는 경우)는 `recompute_queue`에 남길 account_id/instrument_id가 없어 대신 `UnresolvedFillLineageError`를 던지고 `computation_run.status='failed'`만 기록한다 — 이 경로는 예외로 즉시 드러나므로 조용히 넘어가지 않는다는 원칙은 유지된다. `recompute_queue`/`recompute_required` 항목을 실제로 소진하는 배치(위 문단의 "복구")는 아직 구현되지 않았다.

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

- ~~`process_pending_queue()`를 주기적으로 호출하는 스케줄러/운영 자동화 연결~~ — `scripts/run_realized_pnl_recompute_worker.py` + `docker-compose.yml`의 `realized-pnl-recompute-worker` 서비스로 연결 완료(위 상단 상태 배너 참고).
- 대규모 backfill CLI — 이번 recompute 서비스는 `recompute_queue`에 이미 등록된(또는 명시적으로 지정된) 계좌×종목 단위로만 동작한다. "전체 계좌×종목을 순회하며 최초 백필"하는 별도 CLI/러너는 아직 없다.
- BUY fill의 non-adjacent 중복 재적용을 막는 fill 단위 적용 이력(별도 apply-log 또는 적용된 fill_event_id 집합) — 실시간 반영 경로(`RealizedPnlLedgerService.apply_fill`)는 여전히 "가장 최근에 적용된 fill"만 dedup 앵커로 쓴다(6절). recompute/replay 경로는 이 문제에 영향받지 않는다(위 상단 상태 배너 참고).
- `OrderQuery`에 `instrument_id` 필터 추가 검토 — 현재 recompute의 fill 수집은 계좌 전체 주문을 가져온 뒤 애플리케이션에서 종목으로 거른다(`realized_pnl_recompute_service.py` 모듈 docstring "알려진 한계").
- daily aggregate phantom 값(활동이 전혀 없는 날짜에 남은 잘못된 합계) 감사/정리 도구.
- ~~종목별 누계/체결별/일자별 조회 API 구현~~ — `src/agent_trading/api/routes/realized_pnl.py`로 연결 완료(위 상단 상태 배너 참고).
- Admin UI 노출 화면 — **화면 설계서 작성이 먼저 필요하며, 시작 전 사용자에게 먼저 알린다.**
- `broker_fill_snapshots`와의 정식 대사 리포트 및 임계값 정책.
- FIFO 병행 지원(세무 목적 필요 시 별도 lot 테이블 추가).
- ~~매입(BUY) 수수료를 평균단가 계산에 포함하는 방식 검토(현재 v1은 미반영, 3.3절)~~ — **평균단가에는 포함하지 않고 별도 pool 배분 방식으로 구현 완료(14절)**.
- 숏 포지션 지원 여부 검토(현재는 계산 엔진이 예외로 실패만 하고, orchestration은 recompute_queue로 격리만 한다 — 지원 여부 자체는 미결정).
- websocket fill writer 존재 여부 확인 후, 필요 시 5절 정렬 키 설계 재검토.

## 13. `fee_tax_source` provenance 4값 확장 설계 (계약 확정, 구현 미착수)

### 13.0 이 절의 성격 — 왜 문서로 먼저 고정하는가

> **요약(3~6줄)**: 지금까지 `fee_tax_source`는 `reported`/`assumed_zero` 2값뿐이라 "정책이 없어서 0"과 "이 자산군은 애초에 계산 대상이 아니어서 0"을 구분하지 못했다. 이 구분이 없으면 향후 KOSPI/KOSDAQ `kr_stock` 외 자산군(예: 이미 DB에 1,145건 존재하는 `kr_etf`)이 실제로 거래되는 순간, 아무 경고 없이 부정확한 gross 값이 net처럼 노출될 위험이 있다. 그래서 `calculated_from_policy`/`policy_not_applicable`를 더한 4값 체계로 확장하기로 했다. repository 계층(postgres/memory)은 이미 provenance를 제네릭하게(enum 값 그대로) 다루도록 짜여 있어 **이번 확장만으로는 코드 수정이 필요 없다** — 실제로 손대야 하는 곳은 enum 정의, migration, API 응답 계약뿐이다. 계산 로직 자체를 구현하기 전에, 값 체계·저장 스키마·API 계약을 먼저 문서로 고정해 두면 다음 구현 turn이 "왜 이 4값인지"를 다시 논의하지 않고 바로 착수할 수 있다.

이 절은 **read-only 코드/스키마 조사와 여러 차례의 설계 검토 turn을 거쳐 합의된 결정**을 기록한 것이다. 이번 문서화 turn 자체는 코드/migration/DB를 전혀 바꾸지 않았다 — 아래 내용은 전부 "다음 구현 turn이 그대로 따라야 할 계약"이며, 구현이 완료되면 이 절 상단에 "구현 현황" 배너를 추가하는 것이 이 문서 세트의 기존 관례(14/15/16번 문서와 동일)다.

### 13.1 설계 결정 — 4값 체계

`trading.realized_pnl_events.fee_tax_source`(및 `RealizedPnlFeeTaxSource` enum, [`domain/enums.py`](../../../src/agent_trading/domain/enums.py))를 아래 4값으로 확장한다.

| 값 | 의미 |
|---|---|
| `reported` | 브로커가 fee/tax를 **직접** 보고한 값(현재 실시간 경로는 항상 `None`이라 사실상 미발생 — 향후 브로커 응답 개선 시를 위해 유지) |
| `calculated_from_policy` | 지원 대상 자산군·시장군이고, 활성 정책값이 있어 **우리가 계산**한 값 |
| `assumed_zero` | 지원 대상 자산군인데 **정책이 아직 없거나 비활성**이라 0으로 간주한 값 |
| `policy_not_applicable` | **이 정책의 지원 대상 자산군/시장군이 애초에 아니라서** 계산을 시도조차 하지 않은 경우 |

> **[추가 turn] 5번째 값 `historical_policy_estimate` 신설**: initial backfill이 명시적 opt-in 옵션으로 BUY fee를 현재 활성 정책으로 소급 추정할 때만 쓰인다(위 4값과 절대 안 섞임 — `calculated_from_policy`는 "그 시점 실제 활성 정책"이라는 인과관계이고 이 값은 "나중에 소급 추정"이라는 다른 인과관계). 상세는 [`16_broker_fill_snapshot_historical_backfill_design.md`](16_broker_fill_snapshot_historical_backfill_design.md) §8.9, [`domain/enums.py`](../../../src/agent_trading/domain/enums.py). 이 절의 제목/아래 표는 그 이후 다시 갱신하지 않았으므로 "4값"이라는 표현은 이제 "5값 중 실시간 계산 경로에 쓰이는 4값"으로 읽어야 한다.

4값(실시간 경로 기준)은 **서로 배타적**이다 — 하나의 `realized_pnl_event`는 정확히 하나의 provenance만 가진다. 판정 순서는 항상 "① 자산군/시장군이 정책 지원 대상인가 → ② (지원 대상이면) 활성 정책이 있는가"이며, ①에서 탈락하면 무조건 `policy_not_applicable`, ①을 통과하고 ②에서 탈락하면 `assumed_zero`다 — 이 우선순위를 코드가 뒤집으면 안 된다(예: 정책이 없다고 먼저 판단해 `assumed_zero`를 주고 자산군 확인을 건너뛰면, ETF 체결이 "정책 등록만 하면 해결되는 것"으로 잘못 보인다).

**`reported`의 0과 `assumed_zero`의 0은 의미가 다르다.** 전자는 "브로커가 실제로 0원이라고 확정해 준 값"이고, 후자는 "우리가 모른다는 뜻으로 0을 채운 값"이다. 두 값이 숫자로는 똑같이 `0`이어도, provenance가 다르면 신뢰 수준이 완전히 다르다 — 이게 애초에 provenance 필드가 존재하는 이유다.

### 13.2 경계 규칙 — `assumed_zero` vs `policy_not_applicable`

| 상황 | provenance |
|---|---|
| 지원 자산군(코스피/코스닥 `kr_stock`)인데 정책이 아직 등록/활성화되지 않음 | `assumed_zero` |
| 애초에 정책 대상이 아닌 자산군/시장군(예: `kr_etf`, `market_segment` 미분류) | `policy_not_applicable` |
| 브로커가 fee/tax를 명시적으로 0으로 보고 | `reported`(값은 0이어도 provenance는 reported) |
| 브로커가 필드 자체를 안 줘서(`None`) 0으로 간주 + 지원 자산군인데 정책 없음 | `assumed_zero` |

우선순위 규칙(13.1 재확인): **자산군/시장군 지원 여부 확인이 항상 먼저이고, 정책 존재 여부 확인은 그다음이다.**

### 13.3 저장 계층 영향 — 확인된 사실

- `RealizedPnlEventEntity.fee_tax_source`([`domain/entities.py`](../../../src/agent_trading/domain/entities.py))는 **`RealizedPnlFeeTaxSource` enum 타입**이다(단순 `str`이 아님).
- [`db/row_mapper.py`](../../../src/agent_trading/db/row_mapper.py)의 `row_to_entity()`가 "DB의 `str` 값 → 해당 `Enum` 서브클래스로 자동 변환"을 **이미 제네릭하게** 처리한다(`enum_type(value)` 호출) — 이 로직은 특정 enum 값을 나열하지 않으므로, `RealizedPnlFeeTaxSource`에 새 멤버가 추가돼도 **코드 수정 없이 그대로 동작**한다.
- [`repositories/postgres/realized_pnl_events.py`](../../../src/agent_trading/repositories/postgres/realized_pnl_events.py)의 `add()`/`upsert()`는 `event.fee_tax_source.value`만 쓰고 특정 값 분기가 없다.
- [`repositories/memory.py`](../../../src/agent_trading/repositories/memory.py)의 `InMemoryRealizedPnlEventRepository`는 entity 객체를 그대로 저장/치환할 뿐이다.
- **결론(확정 사실)**: 이번 provenance 확장만으로는 위 두 repository 파일에 **코드 수정이 필요 없다.** 실제로 바뀌어야 하는 곳은 `domain/enums.py`(멤버 추가), migration(컬럼 폭 + CHECK), API 스키마/라우트뿐이다.

### 13.4 migration 방향 (설계 수준 — 실제 SQL 최종본 아님)

- **현재 상태**: `realized_pnl_events.fee_tax_source`는 `VARCHAR(16)`, CHECK는 `IN ('reported', 'assumed_zero')`([`db/migrations/0053_add_realized_pnl_ledger_tables.sql`](../../../db/migrations/0053_add_realized_pnl_ledger_tables.sql)).
- **문제**: `calculated_from_policy`(22자), `policy_not_applicable`(21자) 둘 다 16자를 초과한다 — CHECK 값 목록만 바꾸면 컬럼 길이 자체에 막혀 INSERT가 실패한다.
- **권장 방향**: `VARCHAR(32)`로 확장한다. 현재 최장 후보(22자)에 여유를 더한 값이며, `VARCHAR(64)`처럼 과하게 잡지 않는다 — 이 필드는 고정된 소수의 열거값만 담으므로 여유를 최소한으로만 둔다.
- **권장 순서**(신규 migration, `0053` 후속 번호):
  1. 기존 CHECK 제약(`ck_realized_pnl_events_fee_tax_source`) 제거.
  2. 컬럼 타입을 `VARCHAR(16)`에서 `VARCHAR(32)`로 확장(폭을 넓히는 변경이므로 기존 값 `reported`/`assumed_zero`는 그대로 들어간다 — 데이터 손실/변환 문제 없음).
  3. 새 CHECK 제약을 4값(`'reported'`, `'assumed_zero'`, `'calculated_from_policy'`, `'policy_not_applicable'`)으로 재추가.
- **rollback 시 고려사항**: 새 값(`calculated_from_policy`/`policy_not_applicable`)이 이미 저장된 상태에서 컬럼을 다시 `VARCHAR(16)`으로 되돌리려 하면 실패한다 — rollback 스크립트는 "새 값이 실제로 쓰인 행이 있는지 먼저 확인하고, 있으면 rollback을 거부"하는 가드를 포함해야 한다. **다만 이 가드의 정확한 SQL은 이번 문서화 turn에서 확정하지 않는다 — 다음 구현 turn의 과제로 남긴다(13.6절).**

### 13.5 API 계약

- `RealizedPnlEventView.fee_tax_source: str`([`api/schemas.py`](../../../src/agent_trading/api/schemas.py)) 구조는 **유지 가능**하다 — 값 종류가 늘 뿐 필드 타입은 그대로다. 다만 **기존 UI/클라이언트가 새 값(`calculated_from_policy`/`policy_not_applicable`)을 만났을 때 안전하게(최소한 크래시 없이) 처리하는지는 별도로 확인이 필요하다** — 이번 문서화 turn에서 그 확인까지 마친 것은 아니다.
- 집계 응답(`RealizedPnlDailyAggregateView` 등, [`api/routes/realized_pnl.py`](../../../src/agent_trading/api/routes/realized_pnl.py))에는 **`provenance_breakdown`을 4키 고정 딕셔너리로 추가하는 것을 기본안으로 한다**:
  ```json
  {
    "reported": 0,
    "assumed_zero": 1,
    "calculated_from_policy": 3,
    "policy_not_applicable": 0
  }
  ```
  - 배열이 아니라 **딕셔너리**를 쓴다 — 소비자가 `breakdown.calculated_from_policy`로 바로 접근 가능하고, 순서/중복 문제가 없다.
  - **4키는 항상 전부 포함한다**(0건이어도 키 자체는 유지) — 그래야 "이 값이 없어서 안 보이는지, 응답에서 빠진 것인지"를 소비자가 헷갈리지 않는다.
  - **이번 최소 계약은 건수(count) 기준만 다룬다** — 금액 합계 breakdown은 13.6절 미확정 사항이다.
  - 대안으로 "provenance 미노출 유지"/"대표 provenance 1개만 노출"도 검토했으나, 전자는 "gross인데 net이라 불리는" 원래 문제를 방치하고 후자는 여러 provenance가 섞였을 때 임의 규칙이 필요해져 기각했다.

### 13.6 아직 확정하지 말아야 할 사항

- `fee_tax_source_label`(사람이 읽는 설명 문자열) 필드 도입 여부.
- `provenance_breakdown`에 금액 합계까지 포함할지 여부(이번엔 건수만).
- rollback guard의 정확한 SQL.
- 프런트/Admin UI에서 `policy_not_applicable`을 어떤 문구/경고로 노출할지.
- 실제 fee/tax 계산 함수(정책값 기반 산출 로직) 연결 시점과 구현 상세 — 이 절은 provenance/저장/계약만 다루고 계산 로직 자체는 범위 밖이다.
- `execution.fee_tax`라는 `config_versions` 정책 스키마 네임스페이스명과 세부 필드(별도 검토 turn에서 초안이 나왔으나, 이 절의 확정 대상이 아니다).

### 13.7 구현 선후관계

1. **provenance 4값 확정**(이 절, 완료) → 2. **migration 설계/적용**(13.4절 방향 확정, 실제 SQL 작성·실행은 다음 turn) → 3. **API 계약 확정/구현**(13.5절 방향 확정, 실제 스키마·라우트 수정은 다음 turn) → 4. **계산 함수 연결**(범위 밖, 별도 turn) → 5. **실제 구현/운영 반영**.

이 순서가 맞는 이유: provenance 값 체계가 확정되지 않은 채 계산 함수부터 만들면 나중에 분기 로직을 다시 바꿔야 하고, migration 없이 API 계약만 먼저 정하면 실제로 그 값을 저장할 수 없는 상태에서 계약을 확정하게 된다 — 값→저장 스키마→계약→계산의 의존 순서를 그대로 따른 것이다.

## 14. 매수(BUY) 수수료 pool 배분 — C안 확장형(구현 완료)

### 14.0 이 절의 성격

12절 "향후 확장 범위"의 "매입(BUY) 수수료를 평균단가 계산에 포함하는 방식 검토(현재 v1은 미반영, 3.3절)" 항목에 대한 별도 검토 turn의 설계 결정과 그 구현을 기록한다. **`average_cost`는 절대 바꾸지 않는다** — 대신 매수 수수료를 별도 pool로 누적했다가 매도 시점에 보유수량 대비 매도수량 비율로 배분해 `realized_pnl_net`에만 반영하는 절충안(검토 시 비교한 안 A/B/C 중 "안 A 확장형" — 상태 저장 위치는 `position_cost_basis_state`에 두고 lot 원장은 별도로 만들지 않음)이다.

### 14.1 설계 결정

- `average_cost`(및 `avg_cost_basis_before`, `buy_amount_sum`)의 계약은 **전혀 바꾸지 않는다** — 3.2절/3.3절 공식 그대로.
- `realized_pnl_gross` 계약도 바꾸지 않는다.
- `position_cost_basis_state`에 `remaining_buy_fee_pool`(현재 보유 수량에 대응하는, 아직 배분되지 않은 누적 매수 수수료)과 `buy_fee_pool_provenance`(pool의 fee_tax_source 요약, 3값)를 추가한다.
- `realized_pnl_events`에 `allocated_buy_fee`(이번 SELL에 배분된 몫)와 `buy_fee_allocation_source`(배분 시점 pool provenance 스냅샷)를 추가한다. 기존 `fee`(이번 SELL 자체의 매도 수수료)와는 절대 합쳐 넣지 않고 분리 보존한다.
- `realized_pnl_net = realized_pnl_gross - fee - tax - allocated_buy_fee`.

### 14.2 배분 공식

```
전량 청산(sell_quantity == 보유수량):
    allocated_buy_fee = remaining_buy_fee_pool  (비율 계산 없이 전액)
    new_pool = 0

부분 청산:
    allocated_buy_fee = remaining_buy_fee_pool * (sell_quantity / 보유수량)
    new_pool = remaining_buy_fee_pool - allocated_buy_fee
```

이동평균 원가 모델에서는 보유수량 전체가 동일한 `average_cost`를 공유하므로 "수량 비례"와 "원가금액 비례"가 수학적으로 항상 같다 — 수량 비례가 나눗셈에 `average_cost`를 요구하지 않아 더 단순하다. 전량 청산을 별도 분기로 처리하는 이유는 rounding 누적으로 마지막에 pool이 정확히 0이 안 되는 drift를 원천 차단하기 위함이다(`tests/services/test_realized_pnl_engine.py`의 `test_repeated_partial_sells_drain_pool_to_zero_on_final_liquidation` 참고).

### 14.3 provenance 요약 — lot 추적이 아니다

이동평균은 BUY를 개별 lot으로 구분하지 않으므로, `buy_fee_pool_provenance`도 "어느 BUY에서 왔는지"가 아니라 "지금 쌓인 pool 전체가 어떤 신뢰도로 구성돼 있는가"만 요약한다:

- `fully_calculated` — 현재 보유의 최초 진입 이후 쌓인 모든 BUY fee가 `calculated_from_policy`(또는 `reported`, 실 도입 시)로만 구성.
- `fully_assumed_zero` — 전부 `assumed_zero`/`policy_not_applicable`(사실상 0)로만 구성.
- `partially_assumed_zero` — 같은 보유 기간에 위 두 종류가 섞여 들어온 경우. 한 번 섞이면 전량 청산 후 재진입 전까지 "순수"로 되돌아가지 않는다(`realized_pnl_engine._merge_buy_fee_pool_provenance()`).

### 14.4 forward-only 안전성

오늘까지 존재하는 모든 BUY는 fee가 `NULL`이거나(과거 데이터) `assumed_zero`/`policy_not_applicable`(fee=0, `_validate_fill`이 `fee_tax_source=assumed_zero ⟹ fee=0` 불변식을 이미 강제)이므로, 이 확장 공식에 과거 replay 입력을 그대로 흘려도 `+0`을 더하는 것과 같아 결과가 전혀 바뀌지 않는다(`test_past_fee_zero_buys_are_no_op_regression`). 소급 재계산/대량 backfill은 필요 없다 — 신규 컬럼에 기본값(`0`/`fully_assumed_zero`)만 채우면 그대로 진실이다. 단, 이 안전성은 "설계가 forward-only를 보장해서"가 아니라 "지금까지 실제 nonzero 과거 fee가 없어서" 성립하는 것이라는 점을 명확히 인지해야 한다(향후 `reported`가 실제 도입돼 과거 fee가 소급 채워지는 경로가 생기면 재검토 필요).

### 14.5 API 영향

`GET /performance/realized-pnl/events`(`RealizedPnlEventView`)에 `allocated_buy_fee`/`buy_fee_allocation_source`를 추가 노출했다(from_attributes 방식이라 route 코드 변경 없이 스키마 필드 추가만으로 반영). `positions`/`daily`/`summary`/`daily-summary` 응답과 `average_cost`/`avg_cost_basis_before`/`buy_amount_sum`/`fee_tax_sum` 계산식은 전혀 바꾸지 않았다 — `realized_pnl_net`(과 그 합계)만 자연스럽게 영향을 받는다.

### 14.6 구현 위치

- `domain/enums.py`: `RealizedPnlBuyFeeAllocationSource`(3값).
- `domain/entities.py`: `PositionCostBasisStateEntity.remaining_buy_fee_pool`/`buy_fee_pool_provenance`, `RealizedPnlEventEntity.allocated_buy_fee`/`buy_fee_allocation_source`.
- `services/realized_pnl_engine.py`: `_apply_buy()`/`_apply_sell()` 확장, `_merge_buy_fee_pool_provenance()` 신설.
- `db/migrations/0059_add_buy_fee_pool_allocation.sql`.
- `repositories/postgres/position_cost_basis_states.py`, `repositories/postgres/realized_pnl_events.py`, `repositories/memory.py`: INSERT/upsert 컬럼 목록 반영.
- `api/schemas.py`: `RealizedPnlEventView` 필드 추가.
- 단위 테스트: `tests/services/test_realized_pnl_engine.py`(pool 누적/배분/전량청산/과거데이터 회귀/mixed provenance/replay 결정론).

### 14.7 아직 확정하지 않은 것

- 실제 `calculated_from_policy` BUY/SELL 표본으로의 실측 검증(운영 데이터 미존재, 이번 turn은 코드/테스트 범위로 한정).
- `reported`(브로커 실보고 BUY fee) 도입 시 `_CALCULATED_ISH_FEE_TAX_SOURCES` 분류가 여전히 타당한지 재검토.
- Admin UI에 `allocated_buy_fee`/`buy_fee_allocation_source` 노출 여부(이번 turn 범위 밖).
