# KIS 실체결 기준 이동평균 실현 손익(Realized PnL) 도입 — 실행 계획

> **문서 성격**: 설계·실행 계획 문서다. 이 문서 자체는 어떤 코드도 변경하지 않는다. 구현 지시가 아니라 "무엇을, 왜, 어떤 순서로, 어떻게 검증할지"를 확정하는 계획이다.
> **상세 설계**: [`12_realized_pnl_moving_average_ledger.md`](../00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md)
> **연관 문서**: [`03_data_model_erd.md`](../00_foundational_design/detailed_design/03_data_model_erd.md), [`paper_performance_metrics.md`](../09_paper_trading_validation/paper_performance_metrics.md)

## 1. 문제 배경과 현재 한계

이 저장소는 이미 KIS 실체결을 두 경로로 관측하고 있다.

- `trading.fill_events` — [`order_sync_service.py:1444-1549`](../../src/agent_trading/services/order_sync_service.py)의 `_sync_fills()`가 `broker.get_fills()` 결과를 REST 폴링(`source_channel="rest_poll"`)으로 저장. `broker_order_id + broker_fill_id` 우선, 없으면 `(broker_order_id, fill_timestamp, fill_price, fill_quantity)` 복합키로 dedup.
- `trading.broker_fill_snapshots` — [`fill_history_sync.py`](../../src/agent_trading/services/fill_history_sync.py)가 KIS VTTC0081R(일별체결조회)을 자체 `dedupe_key`로 upsert. 관측/백필 목적의 별도 테이블이며, `fill_events`와 독립적으로 채워진다.

`fill_events.source_channel` CHECK 제약은 스키마상 `'websocket' | 'rest_poll' | 'backfill' | 'manual'` 4가지를 허용하지만, 이번 조사에서 확인한 confirmed writer는 `_sync_fills()`의 REST 경로(`rest_poll`)뿐이다. 별도의 websocket fill writer가 존재하는지는 확인하지 못했다. 따라서 **1차 구현(1~3단계)은 REST 기반 fill 입력만을 전제로 진행한다.**

그런데 이 두 소스로부터 **종목별 이동평균 매입원가 기준 실현 손익을 계산·보관하는 로직은 존재하지 않는다.** 현재 실현 손익으로 노출되는 값은 [`performance_summary.py`](../../src/agent_trading/services/performance_summary.py)의 `calc_realized_pnl_for_order()` / `_calc_per_fill_pnl()`이며, 그 계산은 다음과 같다.

```python
multiplier = -1 (BUY) / +1 (SELL)
total += fill_price * fill_quantity * multiplier - fee - tax
```

이것은 **원가를 차감하지 않는 단일 주문 자체의 현금흐름**이다. SELL 주문의 fill만 보고 `+매도금액 - fee - tax`를 반환할 뿐, 그 매도 수량에 대응하는 매입원가를 전혀 조회하지 않는다. 계좌 전체를 합산했을 때 포지션이 정확히 0으로 수렴하는 구간에서는 net cash flow가 결국 손익과 근접하게 수렴하지만, 종목별·기간별·부분매도 단위로 보면 이 값은 실제 실현 손익이 아니라 **주문 단위 현금흐름 근사치**다. 이 한계는 이미 [`paper_performance_metrics.md:27-34`](../09_paper_trading_validation/paper_performance_metrics.md)에 "per-order 기준"이라는 이름으로 공식 문서화되어 있으며, `winning_trade_count`/`losing_trade_count`/`profit_factor` 등 여러 지표가 이 값을 그대로 소비한다([`/performance-summary`, `/performance-metrics`](../../src/agent_trading/api/routes/performance.py)).

또한 `trading.position_snapshots.average_price`([`0001_initial_schema.sql:179-192`](../../db/migrations/0001_initial_schema.sql))는 **KIS가 폴링 시점에 보고하는 브로커 원장 평균단가**이며, 우리가 체결 이벤트로부터 계산한 이동평균이 아니다. 두 값을 같은 개념으로 취급하면 안 되고, 향후 대사(reconciliation) 대상으로 명확히 구분해야 한다.

## 2. 왜 지금 필요한가

- 종목별로 얼마를 벌고 잃었는지에 대한 신뢰 가능한 숫자가 없으면 전략/holding_profile/trigger 단위 성과 귀속(attribution) 지표(`docs/09_paper_trading_validation/*`, `performance.py`의 attribution endpoint들)의 해석이 왜곡된다.
- paper 운용 Go/No-Go 게이트([`GateEvaluationService`](../../src/agent_trading/services/gate_evaluation.py))가 궁극적으로 참조할 손익 지표의 정확도를 지금 확정하지 않으면, 이후 라이브 전환 판단의 근거가 흔들린다.
- 부분매도·분할체결·재매수가 실제로 빈번한 KIS 실거래 패턴이므로, per-order 근사가 만드는 오차가 누적될수록 나중에 재작업 비용이 커진다.

## 3. 구현 단계별 계획

이 실행 계획은 **1차 범위(계산 엔진 + 저장 + 실시간 반영)** 와 **후속 확장(백필, 조회 API, 화면, 대사)** 를 명확히 분리한다. 각 단계는 별도 PR로 나눌 것을 전제로 한다.

### 0단계 — 전제 확인 (구현 착수 전, read-only)

- 왜: 상세 설계 문서([`12_realized_pnl_moving_average_ledger.md`](../00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md) 2절)에 정리한 미확인 가정 — REST 기반 입력 경로 확정을 전제로 했을 때 그와 별개로 websocket fill writer가 존재하는지 여부, 국내주식 계좌의 숏 포지션 발생 가능성, admin_ui의 실현 손익 소비 화면 범위 — 을 실제 구현 전에 검증해야 스키마 재작업을 피할 수 있다.
- 산출물: 확인 결과 요약(짧은 코멘트 또는 이슈, 별도 보고서 문서 생성은 하지 않음).
- 검증 기준: 사용자에게 전제가 맞는지 1회 확인받는다.

### 1단계 — 계산 엔진(순수 함수)

- 왜: DB나 repository 없이 독립적으로 검증 가능한 부분을 먼저 고정해야 이후 단계의 리스크가 줄어든다.
- 산출물: 상세 설계 문서 3.2절의 상태 전이 함수(`apply_fill_to_cost_basis` 등) + 단위 테스트. 매수/매도/부분매도/같은 날 교차/완전청산 원가 리셋/재매수/fee·tax 반영/중복 fill 재적용 no-op 시나리오 포함.
  - **구현 완료**: [`src/agent_trading/services/realized_pnl_engine.py`](../../src/agent_trading/services/realized_pnl_engine.py)(`apply_fill_to_cost_basis()`, `replay_fills()`, 전용 예외 7종) + [`tests/services/test_realized_pnl_engine.py`](../../tests/services/test_realized_pnl_engine.py)(21개 assert 케이스, parametrize 포함). 저장소를 호출하지 않는 순수 함수이며, `order_sync_service` 연결·backfill 러너·API 연동은 아직 없다(3단계 이후).
- 검증 명령: `bash scripts/harness/run.sh accept backend-file <새 파일 경로>`, `bash scripts/harness/run.sh test-file tests/services/test_<신규 파일>.py`.

### 2단계 — DB 스키마 / 엔티티 / repository

- 왜: ledger 저장 계층을 실시간 반영과 분리해 먼저 만들어야 3단계 연결이 안전하다.
- 산출물: `trading.position_cost_basis_state`, `trading.realized_pnl_events`, `trading.realized_pnl_daily_aggregates`, `trading.realized_pnl_computation_runs`, `trading.realized_pnl_recompute_queue` 마이그레이션(상세 설계 문서 4절) + entity + repository contract/구현.
  - **마이그레이션 초안 작성 완료**: [`db/migrations/0053_add_realized_pnl_ledger_tables.sql`](../../db/migrations/0053_add_realized_pnl_ledger_tables.sql)(신규 테이블 5종), [`db/migrations/0054_add_realized_pnl_support_indexes.sql`](../../db/migrations/0054_add_realized_pnl_support_indexes.sql)(보조 인덱스, `order_requests` 비파괴적 인덱스 1건 포함). 어떤 DB에도 아직 실행되지 않았고, entity/repository/runtime 코드는 아직 없다.
- 검증 명령: `bash scripts/harness/run.sh accept db-structure`, 신규 repository 단위 테스트.

### 3단계 — 실시간 반영 연결

- 왜: `_sync_fills()`가 `fill_events`에 새 행을 append하는 지점에서 ledger를 함께 갱신해야 "체결 기준" 요구사항이 충족된다.
- 산출물: fill 저장 성공 후 ledger 갱신 호출 + 실패 시 복구 계약(상세 설계 문서 8절 — 재처리 큐/`recompute_required`/운영 지표 중 최소 하나를 반드시 포함).
  - **orchestration 서비스 + `order_sync_service` 훅 연결 모두 구현 완료**: [`src/agent_trading/services/realized_pnl_ledger_service.py`](../../src/agent_trading/services/realized_pnl_ledger_service.py)의 `RealizedPnlLedgerService.apply_fill()`이 fill → NormalizedFill 정규화(join 포함) → 계산 엔진 호출 → state/event/일자집계 저장 → 실패 시 recompute_queue/recompute_required 처리를 전부 구현했다(단위 테스트: [`tests/services/test_realized_pnl_ledger_service.py`](../../tests/services/test_realized_pnl_ledger_service.py)). [`order_sync_service._sync_fills()`](../../src/agent_trading/services/order_sync_service.py)는 REST 기반(`get_fills()`) dedup을 통과한 **신규** fill 저장 직후에만 이 서비스를 호출하고, 실패는 fill 저장과 분리해 로그(`applied`/`skipped_duplicate`/`recompute_required`/`failed` 집계)로 관측 가능하게 처리한다(단위 테스트: `tests/services/test_order_sync_service.py`의 `TestRealizedPnlLedgerHook`).
  - idempotency 한계: SELL은 `fill_event_id` UNIQUE 조회로 완전 방어, BUY는 "가장 최근 적용 fill과의 일치"만 방어(상세 설계 문서 6절). 이 한계는 훅 연결 이후에도 그대로 유지된다.
- 검증 명령: `bash scripts/harness/run.sh accept backend-runtime`, 모킹된 broker 기반 통합 테스트.

### 4단계 — 백필(backfill) / recompute 복구 — 핵심 replay 및 운영 경로 연결 완료, 대규모 backfill CLI는 미착수

- 왜: 이동평균은 계좌×종목별 전체 히스토리를 시간순으로 처음부터 replay해야 정확하므로(중간 지점 재계산 불가), 과거분 재계산은 신규 체결 반영과 독립된 별도 작업으로 분리한다.
- 산출물: `realized_pnl_computation_runs(run_type='backfill_replay')` 단위 계좌×종목 replay.
  - **구현 완료**: [`src/agent_trading/services/realized_pnl_recompute_service.py`](../../src/agent_trading/services/realized_pnl_recompute_service.py)의 `RealizedPnlRecomputeService`. `recompute_account_instrument(account_id, instrument_id)`가 해당 계좌×종목의 fill 히스토리를 정렬해 `replay_fills()`로 재계산하고 저장소에 반영하며, `process_pending_queue()`가 `realized_pnl_recompute_queue` pending 항목을 계좌×종목 단위로 coalesce해 이를 반복 호출한다(단위 테스트: [`tests/services/test_realized_pnl_recompute_service.py`](../../tests/services/test_realized_pnl_recompute_service.py)).
  - **운영 경로 연결도 완료**: [`scripts/run_realized_pnl_recompute_worker.py`](../../scripts/run_realized_pnl_recompute_worker.py)가 `process_pending_queue()`를 주기 호출하는 독립 장기 실행 워커다(`reconciliation-worker`와 동일한 패턴, `docker-compose.yml`의 `realized-pnl-recompute-worker` 서비스로 배포). 계산/replay 로직 자체는 이 연결 작업에서 수정하지 않았다(단위 테스트: [`tests/scripts/test_run_realized_pnl_recompute_worker.py`](../../tests/scripts/test_run_realized_pnl_recompute_worker.py)).
  - **미착수**: "전체 계좌×종목을 처음부터 순회하는" 대규모 backfill CLI(현재는 이미 `recompute_queue`에 등록된 대상만 처리한다), API, Admin UI.
- 검증 명령: 소수 계좌 dry-run → 사용자 승인 → 전체 실행. 실제 DB에 대한 배치 실행 자체는 `AGENTS.md` 검증 부하 제한에 따라 **사용자 명시 승인 필요**(recompute 서비스 자체 및 워커 연결 모두 in-memory repository/모킹 테스트로만 검증했다).

### 5단계 — 조회 API — 구현 완료(read-only)

- 왜: "계산 엔진"과 "조회 API"를 분리해야 한다는 요구사항에 따라 API는 ledger를 읽기만 한다.
- 산출물: [`src/agent_trading/api/routes/realized_pnl.py`](../../src/agent_trading/api/routes/realized_pnl.py)에 4개 read-only endpoint를 추가했다.
  - `GET /performance/realized-pnl/positions` — `account_id`(필수) + `instrument_id`(선택, 생략 시 계좌 전체). authoritative source: `position_cost_basis_state`(수량/평균단가/`recompute_required`/`recompute_reason`) + `realized_pnl_daily_aggregates` 합산(`realized_pnl_net_cumulative`).
  - `GET /performance/realized-pnl/events` — `account_id`+`instrument_id`(둘 다 필수) + `before`/`limit`(선택). authoritative source: `realized_pnl_events`.
  - `GET /performance/realized-pnl/daily` — `account_id`+`instrument_id`(둘 다 필수) + `start_date`/`end_date`(선택). authoritative source: `realized_pnl_daily_aggregates`.
  - `GET /performance/realized-pnl/recompute-queue` — `account_id`/`instrument_id`(둘 다 선택 필터). authoritative source: `realized_pnl_recompute_queue`의 미해결(`resolved_at IS NULL`) 항목.
  - `PositionCostBasisStateRepository.list_by_account()`를 최소 범위로 추가했다(`positions` endpoint가 `instrument_id` 없이 계좌 전체를 나열하려면 필요 — 신규 migration은 없다, 기존 테이블에 대한 조회 메서드 추가뿐).
  - 계산은 전혀 하지 않는다 — `realized_pnl_engine.py`/`realized_pnl_ledger_service.py`/`realized_pnl_recompute_service.py`의 계산 로직을 재구현하지 않았고, `performance_summary.py`의 기존 현금흐름 근사도 교체하지 않았다.
- 단위 테스트: `tests/api/test_inspection.py`의 `TestRealizedPnl`(positions/events/daily/recompute-queue 각각 정상 조회·필터·빈 결과·잘못된 UUID/날짜 케이스).
- 검증 명령: `bash scripts/harness/run.sh accept backend-runtime`, API 계약 테스트. 이번 PR의 실제 실행 결과와 환경 제약은 완료 보고 참고(호스트에 `fastapi`/`pydantic`이 없어 `accept backend-file`/`accept backend-runtime`은 stale docker mount 제약과 겹쳐 완전한 실행 검증을 하지 못했다).

### 6단계 — 운영 화면/기존 지표 정리 — 후속 확장

- 왜: 기존 `AccountPerformanceSummary.realized_pnl`(주문 현금흐름 근사)을 신규 ledger 값과 어떻게 병행/대체할지 결정해야 한다.
- 산출물: admin_ui 반영안, `paper_performance_metrics.md` 갱신.
- 검증 명령: `bash scripts/harness/run.sh accept frontend`, `bash scripts/harness/run.sh accept docs`.

## 4. 단계별 산출물 요약표

| 단계 | 산출물 | 상태 |
|---|---|---|
| 0 | 전제 확인 결과 | 미착수 |
| 1 | 계산 엔진 + 단위 테스트 | **구현 완료**(`realized_pnl_engine.py`, 저장소 미연결) |
| 2 | 신규 마이그레이션(초안)/엔티티/repository | **마이그레이션 초안만 작성 완료**(0053/0054, 미실행) — entity/repository는 미착수 |
| 3 | 실시간 반영 훅 + 복구 계약 | **구현 완료**(`realized_pnl_ledger_service.py` + `order_sync_service._sync_fills()` 훅 연결) |
| 4 | recompute/replay 복구 서비스 + queue 처리 | **핵심 구현 완료 + 운영 경로 연결 완료**(`realized_pnl_recompute_service.py`, `scripts/run_realized_pnl_recompute_worker.py`) — 대규모 backfill CLI는 미착수 |
| 5 | 조회 API | **구현 완료**(`src/agent_trading/api/routes/realized_pnl.py`, read-only) |
| 6 | 화면/문서 정리 | 미착수(후속) — Admin UI는 화면 설계서 선행 필요, 시작 전 사용자에게 먼저 알린다 |

### 마이그레이션 설계 메모 — 왜 이 구성이 최소 안전선인가

`0053_add_realized_pnl_ledger_tables.sql` / `0054_add_realized_pnl_support_indexes.sql`는 다음 이유로 "지금 당장 필요한 최소 범위"로 판단했다.

- **파괴적 변경이 전혀 없다**: 기존 `fill_events`/`order_requests`/`broker_orders`/`position_snapshots`의 컬럼·제약을 하나도 바꾸지 않는다. 신규 테이블 5개 추가와 기존 테이블에 대한 비파괴적 보조 인덱스 1개(`order_requests`) 추가뿐이다. 실패해도 기존 런타임에 영향이 없다.
- **append-only 원칙을 스키마가 직접 강제한다**: `realized_pnl_events`에는 UPDATE 경로를 전제하지 않고, `superseded_by_event_id` self-reference로만 정정이 가능하도록 설계했다. migration 자체가 이 원칙을 깨는 트리거나 규칙을 포함하지 않는다.
- **idempotency의 1차 방어선을 DB 제약으로 고정한다**: `realized_pnl_events.fill_event_id`에 UNIQUE 제약을 걸어, 이후 계산 엔진이 어떤 구현이든 같은 fill을 두 번 반영하면 애플리케이션 로직이 아니라 DB가 막는다.
- **숏 포지션은 임시 가드로 막아 둔다**: `position_cost_basis_state.quantity >= 0` CHECK. 현재는 개인 계좌 기준으로 음수 잔량을 지원 범위에 넣지 않았다는 뜻일 뿐, 장기 정책으로 확정된 것은 아니다. 지금은 계산 엔진 버그가 음수 잔량을 조용히 저장하는 경로를 DB 레벨에서 막아 두고, 실제로 숏 포지션을 지원하기로 결정되면 별도 migration으로 완화한다.
- **관측성을 스키마 차원에서 준비해 둔다**: `realized_pnl_computation_runs`(처리 건수/이상 건수 컬럼)와 `realized_pnl_recompute_queue`(장애 복구 큐)를 실시간 반영 코드(3단계)보다 먼저 만들어 두면, 3단계 구현이 "조용히 실패를 감춘다"는 실수를 할 수 있는 여지를 스키마 단계에서 줄인다.
- **인덱스는 필요한 것만 남겼다**: 사용자가 검토를 요청한 인덱스 후보 중 `fill_events (broker_order_id, fill_timestamp, created_at, fill_event_id)`는 이미 존재하는 `idx_fill_events_broker_order_time (broker_order_id, fill_timestamp DESC)`([`0001_initial_schema.sql:458-459`](../../db/migrations/0001_initial_schema.sql))와 90% 이상 겹치고, btree 인덱스는 역방향(ASC) 스캔도 동일 비용으로 지원하므로 방향 차이가 별도 인덱스를 정당화하지 않는다고 판단해 제외했다. `realized_pnl_computation_runs`는 사용자가 제안한 복합 인덱스 `(started_at DESC, status)` 대신, 기존 `fill_sync_runs`([`0029_add_fill_history_snapshot_tables.sql`](../../db/migrations/0029_add_fill_history_snapshot_tables.sql))와 동일하게 단일 컬럼 인덱스 2개로 분리했다(기존 관례 일치 + status 단독 필터 조회 지원).

이번 migration 초안은 그 자체로 최종 스키마 확정을 의미하지 않는다. 3단계(실시간 반영) 구현 중 계산 엔진의 실제 쿼리 패턴이 드러나면 인덱스는 추가/조정될 수 있다.

## 5. 단계별 검증 명령

- 계산 엔진 단일 파일: `bash scripts/harness/run.sh accept backend-file <file>`
- DB 스키마 변경: `bash scripts/harness/run.sh accept db-structure`
- 런타임 조립/의존성 변경: `bash scripts/harness/run.sh accept backend-runtime`
- 계층 import 경계: `bash scripts/harness/run.sh accept architecture`
- 코드 스타일 baseline: `bash scripts/harness/run.sh accept style`
- 우회 행동 검사: `bash scripts/harness/run.sh accept no-bypass`
- 단일 테스트: `bash scripts/harness/run.sh test-one <selector>`
- 대상 테스트 파일: `bash scripts/harness/run.sh test-file <tests/path.py>`
- 문서 정합성(본 문서 작성 직후 필수): `bash scripts/harness/run.sh accept docs`
- Admin UI 계약(6단계): `bash scripts/harness/run.sh accept frontend`

전체 테스트(`make test`, `python3 -m pytest tests/` 등)와 DB 쓰기/마이그레이션 실행, 백필 배치 실행은 `AGENTS.md`의 검증 부하 제한에 따라 **사용자 명시 승인 없이 실행하지 않는다.**

## 6. 운영 전환 순서

1. 1~3단계 완료 후, **신규 체결부터** ledger가 정상 누적되는지 paper 계좌 1개로 최소 1거래일 관찰.
2. 관찰 결과(관측된 fill 수, ledger 반영 수, `recompute_required` 발생 건수)를 사용자에게 보고하고 확대 여부 승인받는다.
3. 승인 후 전체 paper 계좌로 확대.
4. 백필(4단계)은 별도 승인 절차를 거쳐 신규 반영이 안정화된 뒤에만 진행한다.
5. live 계좌 전환은 이 문서의 범위 밖이며, 별도 라이브 전환 게이트 문서(`docs/09_paper_trading_validation/live_*`) 절차를 따른다.

## 7. 백필 여부와 범위 분리

- **1차 범위(바로 구현 가능)**: 1~3단계만. 신규 체결부터 정확한 ledger가 쌓이기 시작하는 것으로 한정하고, 과거분은 "미계산" 상태임을 조회 API/화면에 명시적으로 표시한다.
- **후속 확장 범위**: 4단계 백필, 5단계 조회 API, 6단계 화면/문서 정리, `broker_fill_snapshots`와의 정식 대사 리포트, FIFO 병행 지원(세무 목적 필요 시), 숏 포지션 지원 여부 검토.

## 8. 리스크 / 보류 이슈

| 이슈 | 내용 | 처리 방침 |
|---|---|---|
| websocket fill writer 존재 여부 미확인 | `fill_events`의 confirmed writer는 현재 조사 범위 기준 REST 기반 `_sync_fills()`(`broker.get_fills()`)이며, `broker_fill_snapshots`는 VTTC0081R 백필/대사 전용 경로다. `fill_events.source_channel` CHECK 제약에 `'websocket'` 값이 스키마상 허용되어 있으나([`0001_initial_schema.sql:361`](../../db/migrations/0001_initial_schema.sql)), 별도의 websocket fill writer가 존재하는지는 확인하지 못했다 | 1차 구현(1~3단계)은 REST 기반 fill 입력만을 전제로 진행. websocket writer 존재가 나중에 확인되면 5절 정렬 키/실시간 반영 설계를 재검토 |
| 숏 포지션 발생 가능성 | 국내주식 paper/live 계좌에서 매도 후 음수 잔량이 발생하는 케이스가 있는지 미확인 | 현재는 개인 계좌 기준으로 음수 잔량을 지원 범위에 넣지 않고, `position_cost_basis_state.quantity >= 0` CHECK를 DB 레벨 임시 가드로 둔다(상세 설계 문서 6절). 장기 정책으로 확정된 것은 아니며, 지원 여부가 결정되면 별도 migration으로 완화한다 |
| 기존 지표와의 병행 기간 | `AccountPerformanceSummary.realized_pnl` 소비처(대시보드, gate evaluation)가 즉시 교체되면 회귀처럼 보일 수 있음 | 6단계에서 신규/기존 값을 함께 노출하고 차이를 설명하는 방식으로 시작(상세 설계 문서 11절) |
| broker_fill_snapshots와의 이중 관측 | 같은 실제 체결이 `fill_events`와 `broker_fill_snapshots` 양쪽에 서로 다른 시점/필드로 기록될 수 있음 | ledger는 `fill_events`만을 1차 입력으로 확정하고, `broker_fill_snapshots`는 대사 전용으로 한정(상세 설계 문서 10절) |

## 9. 완료 기준

이 실행 계획 문서 자체의 완료 기준(구현 완료 기준이 아니라 **문서 작업**의 완료 기준):

- 본 문서와 [`12_realized_pnl_moving_average_ledger.md`](../00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md)가 작성되고, [`03_data_model_erd.md`](../00_foundational_design/detailed_design/03_data_model_erd.md)와 [`detailed_design/README.md`](../00_foundational_design/detailed_design/README.md)가 신규 엔티티/문서를 반영한다.
- `bash scripts/harness/run.sh accept docs` 실행 결과 `required_file_missing_count=0`, `markdown_link_missing_count`가 본 작업으로 새로 발생하지 않는다.
- 구현되지 않은 내용을 구현 완료로 서술한 부분이 없다(전체 문서에 "설계/계획" 상태임을 명시).

이후 1~3단계 구현이 실제로 진행될 때는 이 기준과 별개로 [`definition_of_done.md`](../80_harness_engineering/definition_of_done.md)를 따른다.

### 이번 단계(2단계 — 마이그레이션 초안)의 완료 기준

- `db/migrations/0053_add_realized_pnl_ledger_tables.sql`, `db/migrations/0054_add_realized_pnl_support_indexes.sql`가 작성되고 파일명 번호가 기존 마이그레이션과 충돌/공백 없이 이어진다.
- `bash scripts/harness/run.sh accept db-structure` 결과 `migration_duplicate_number_count=0`, `migration_sequence_gap_count=0`, `migration_filename_violation_count=0`.
- 이 migration은 아직 어떤 DB에도 실행되지 않았다 — "작성 완료"와 "적용 완료"를 구분해서 보고한다.
- entity/repository/runtime 코드는 이번 단계에 포함하지 않는다(2단계의 나머지 부분 + 3단계는 후속 작업).

### 이번 단계(1단계 — 계산 엔진)의 완료 기준

- `src/agent_trading/services/realized_pnl_engine.py`가 저장소를 호출하지 않는 순수 함수로 작성되고, `tests/services/test_realized_pnl_engine.py`가 이 문서/상세 설계 3.2절의 계산 규칙과 불변식을 모두 커버한다.
- 계산 엔진은 저장소를 전혀 몰라야 한다 — `order_sync_service` 연결, backfill 러너, API, Admin UI는 이번 단계에 포함하지 않는다(3단계 이후 후속 작업).
- 이 단계에서 "구현 완료"는 순수 함수와 그 단위 테스트가 통과한다는 뜻이며, 실제 KIS 체결 데이터로의 실측 검증은 아직 이루어지지 않았다.

### 이번 단계(3단계 — repository write orchestration)의 완료 기준

- `src/agent_trading/services/realized_pnl_ledger_service.py`의 `RealizedPnlLedgerService.apply_fill()`이 계산은 전부 `realized_pnl_engine.py`에 위임하고, fill → NormalizedFill 정규화·현재 상태 조회·저장·idempotency·out-of-order/실패 시 recompute_queue·recompute_required 처리를 담당한다.
- `tests/services/test_realized_pnl_ledger_service.py`가 BUY/SELL 반영, fee/tax 정규화, idempotency(SELL 완전 방어/BUY 제한적 방어), 계산 엔진 예외, out-of-order, lineage 조인 실패, computation run 카운트를 in-memory repository 기반으로 커버한다.
- BUY dedup이 "가장 최근 적용 fill과의 일치"만 방어한다는 한계는 완료 기준 위반이 아니라 명시적으로 문서화된 현재 범위다.

### 이번 단계(3단계 — `order_sync_service` runtime 훅 연결)의 완료 기준

- `order_sync_service._sync_fills()`가 REST 기반 dedup을 통과한 **신규** fill 저장 직후에만 `RealizedPnlLedgerService.apply_fill()`을 호출한다 — 이미 dedup되어 저장을 건너뛴 fill에는 호출되지 않는다.
- ledger 훅의 예외/실패는 fill 저장 성공 여부와 분리되어 로그(`applied`/`skipped_duplicate`/`recompute_required`/`failed` 집계, `logger.error(..., exc_info=True)`)로 관측 가능해야 한다 — "fill 저장 성공 후 ledger 실패"가 조용히 성공처럼 보이면 안 된다.
- `tests/services/test_order_sync_service.py`의 `TestRealizedPnlLedgerHook`이 신규 fill 반영/dedup 시 재호출 안 됨/`recompute_required` 로깅/예외 격리/기존 dedup 동작 무변화를 in-memory repository 기반으로 커버한다.
- `RealizedPnlLedgerService`/`realized_pnl_engine.py`의 계산 로직 자체는 이번 단계에서 재구현하지 않는다.
- backfill 러너, `recompute_queue` 소진 배치, API, Admin UI는 이번 단계에 포함하지 않는다.

### 이번 단계(4단계 — recompute/replay 복구 서비스)의 완료 기준

- `src/agent_trading/services/realized_pnl_recompute_service.py`의 `RealizedPnlRecomputeService.recompute_account_instrument()`가 계산은 전부 `replay_fills()`에 위임하고, fill 수집·정렬·저장(upsert)·queue resolve·`recompute_required` 해제를 담당한다. `process_pending_queue()`가 같은 계좌×종목의 pending을 coalesce해 중복 replay를 피한다.
- `tests/services/test_realized_pnl_recompute_service.py`가 정렬 후 replay, out-of-order 상태 해제, queue 부분 resolve(다른 계좌×종목은 그대로 유지), coalesce, collect 단계 실패 시 관측, idempotent 재실행, daily aggregate 절대값 재구성을 in-memory repository 기반으로 커버한다.
- `RealizedPnlEventRepository.upsert()`(recompute 전용, 실시간 경로는 여전히 `add()`만 사용)를 최소 범위로 추가했다 — 이는 "정정은 UPDATE/DELETE 없이 supersede 행 append로"라는 당초 설계를 재검토하게 만든 실제 구현상의 발견이며, 상세 설계 문서 7.3절에 그 경위를 반영했다.
- 스케줄러 연결, 대규모 backfill CLI, API, Admin UI, `performance_summary.py` 교체는 이번 단계에 포함하지 않는다.

### 이번 단계(4단계 후속 — recompute 운영 경로 연결)의 완료 기준

- recompute/replay 계산 로직(`RealizedPnlRecomputeService`, `realized_pnl_engine.replay_fills()`) 자체는 재구현하지 않는다 — 이번 단계는 그 서비스를 실제로 호출하는 운영 경로를 연결하는 것으로 한정한다.
- `scripts/run_realized_pnl_recompute_worker.py`: `reconciliation-worker`와 동일한 "독립 장기 실행 워커가 자체 polling 루프로 pending 큐를 소비" 패턴을 따른다(선택 근거: recompute는 거래 시간대에 종속되지 않는 데이터 품질 유지보수 작업이라 `run_ops_scheduler.py`의 거래시간대 종속 subprocess-cadence 태스크와 성격이 다르고, 이미 같은 문제(pending 큐 소비)를 검증된 형태로 풀고 있는 `reconciliation-worker` 패턴을 복제하는 쪽이 4000줄 규모의 `run_ops_scheduler.py`에 새 태스크를 끼워넣는 것보다 회귀 위험이 낮다).
- 매 사이클 `RealizedPnlRecomputeService.process_pending_queue(limit=...)`를 1회 호출한다(기본 limit=100, `REALIZED_PNL_RECOMPUTE_WORKER_QUEUE_LIMIT`로 조정). 계좌×종목 단위 실패는 서비스 자체가 흡수해 격리하므로(`recompute_account_instrument()`가 예외를 삼켜 `status="failed"` run으로 기록) 한 계좌×종목의 실패가 워커 전체 사이클을 중단시키지 않는다.
- 사이클마다 `recompute_processed_count`/`recompute_completed_count`/`recompute_failed_count`/`recompute_queue_resolved_count`를 구조화 로그로 남기고, 실패한 계좌×종목은 `account_id`/`instrument_id`/`computation_run_id`/실패 사유(summary)를 `WARNING` 레벨로 별도 기록한다 — "조용히 돌아가는 배치"가 되지 않도록 한다.
- `docker-compose.yml`에 `realized-pnl-recompute-worker` 서비스를 `reconciliation-worker`와 동일한 형태(빌드/네트워크/재시작 정책)로 추가했다. 기본 interval은 300초(신규 fill 반영 경로인 `post_submit`의 30초보다 여유 있게, 관측 전용 백필 경로인 `fill_sync`의 600초보다는 조금 짧게 설정 — recompute는 out-of-order 등으로 잘못된 상태가 노출되는 시간을 줄이는 목적이 있어 완전히 후순위로 두지 않았다).
- `tests/scripts/test_run_realized_pnl_recompute_worker.py`가 (1) 워커가 실제로 `process_pending_queue()`를 호출하는지, (2) pending 없음 케이스, (3) 성공/실패 혼재 시 집계, (4) `limit` 전달, (5) 실패 로그 기록을 모킹된 서비스 기준으로 커버한다.
- 대규모 backfill CLI, API, Admin UI는 이번 단계에 포함하지 않는다. **Admin UI 단계로 넘어가기 직전에는 별도로 사용자에게 알린다.**

### 이번 단계(5단계 — 조회 API)의 완료 기준

- 계산 로직은 재구현하지 않는다 — `src/agent_trading/api/routes/realized_pnl.py`의 4개 endpoint는 route가 직접 `RepositoryContainer`를 통해 저장된 값을 읽고, 종목 누계만 `sum()`으로 합산한다(이동평균/실현손익 계산이 아니다).
- 레이어 판단: 별도 read 전용 service를 두지 않고 `positions.py`(`GET /positions`)와 동일하게 route에서 `Depends(get_repos)`로 repository를 직접 조회한다 — 이 4개 endpoint는 순수 조회+필터+합산뿐이라 서비스 계층을 추가하면 오히려 불필요한 간접화가 된다.
- 종목 누계 산정 방식: 체결 상세=`realized_pnl_events`, 일자 요약=`realized_pnl_daily_aggregates`를 각각 authoritative source로 그대로 노출한다. 종목 누계(`realized_pnl_net_cumulative`)는 `realized_pnl_daily_aggregates`(해당 계좌×종목 전체 날짜)의 `realized_pnl_net_sum`을 합산한 값을 authoritative로 채택한다 — `realized_pnl_events`를 매번 전부 훑어 합산하는 대신, 이미 그 목적으로 설계된 파생 캐시를 재사용한다.
- pagination/필터: event 목록은 `limit`(기본 200, 최대 1000) + `before`, daily aggregate는 `start_date`/`end_date` 선택 필터를 그대로 지원한다(기존 repository 메서드 시그니처와 1:1 대응).
- `PositionCostBasisStateRepository.list_by_account()`를 최소 범위로 추가했다 — `positions` endpoint가 `instrument_id` 없이 계좌 전체를 나열하려는 요구를 기존 메서드(`get(account_id, instrument_id)`, `list_recompute_required()`)로는 충족할 수 없어서다. 신규 migration은 없다.
- `recompute_required` 상태는 `positions` endpoint의 같은 필드로 바로 볼 수 있고, `recompute-queue` endpoint는 "왜/언제 큐에 들어갔는지"(`reason_code`/`requested_at`)를 보는 별도 경로로 분리했다.
- `broker_fill_snapshots`는 이번 endpoint들의 조회 대상이 아니다 — 여전히 대사(reconciliation) 전용이다.
- Admin UI, `performance_summary.py` 교체, 신규 migration, backfill CLI 확장은 이번 단계에 포함하지 않는다. **Admin UI는 화면 설계서 작성이 먼저 필요하며, 그 단계로 넘어가기 전에는 사용자에게 먼저 알린다.**

## 10. 추가 보정사항 / 유지해야 할 원칙 / 완료 후 보고 가이드

- 이 문서는 리스크 게이트, sell guard, 주문 제출 의미론을 바꾸지 않는다. ledger는 순수 관측/집계 기능이며 주문 제출 경로에 개입하지 않는다.
- `fill_events`의 기존 dedup 로직([`order_sync_service.py:1490-1529`](../../src/agent_trading/services/order_sync_service.py))은 재발명하지 않고 그대로 신뢰하며, ledger는 그 위에 `fill_event_id` UNIQUE 제약만 추가한다.
- 구현 단계에 들어가면 각 PR의 완료 보고에 반드시 포함할 것: 변경 파일, 실행한 검증 명령과 실제 출력 지표, 처리/스킵/오류 건수, 검증하지 못한 가정, (해당 시) 브랜치/PR/check 상태.
- 백필 실행 결과를 보고할 때는 처리 계좌 수·체결 건수·skip/anomaly 건수·백필 전후 표본 검산 결과를 포함한다. 단순히 "완료"라고만 쓰지 않는다.
