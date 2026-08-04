# 데이터 모델 및 ERD 초안 v1

## 1. 목적

거래, 판단, 설정, 감사, 재현성 데이터를 저장하기 위한 핵심 엔티티를 정의한다.

## 2. 핵심 엔티티 목록

- client
- account
- broker_account
- strategy
- strategy_version
- config_version
- trading_session
- instrument
- market_data_snapshot
- feature_snapshot
- decision_context
- agent_run
- risk_decision
- compliance_decision
- trade_decision
- order_request
- broker_order
- fill_event
- position_snapshot
- cash_balance_snapshot
- reconciliation_run
- audit_log
- model_registry
- prompt_registry
- replay_bundle
- risk_limit_snapshot
- guardrail_evaluation
- order_state_event
- decision_state_event
- broker_api_call_log
- market_data_quality_event
- position_cost_basis_state
- realized_pnl_event
- realized_pnl_daily_aggregate
- realized_pnl_computation_run
- realized_pnl_recompute_queue

## 3. 관계 개요

```text
client 1---N account
client 1---N strategy
strategy 1---N strategy_version
client 1---N config_version

account 1---N trading_session
account 1---N order_request
account 1---N position_snapshot

decision_context 1---N agent_run
decision_context 1---1 risk_decision
decision_context 1---1 compliance_decision
decision_context 1---1 trade_decision

trade_decision 1---N order_request
order_request 1---N broker_order
broker_order 1---N fill_event

reconciliation_run N---N order_request
reconciliation_run N---N position_snapshot

account 1---N position_cost_basis_state
instrument 1---N position_cost_basis_state
fill_event 1---1 realized_pnl_event   (UNIQUE(fill_event_id) — 매도 체결 1건당 최대 1행)
broker_order 1---N realized_pnl_event
realized_pnl_computation_run 1---N realized_pnl_event
realized_pnl_event 0---N realized_pnl_event   (superseded_by_event_id, 정정 시 self-reference)
account 1---N realized_pnl_daily_aggregate
instrument 1---N realized_pnl_daily_aggregate
account 1---N realized_pnl_recompute_queue
instrument 1---N realized_pnl_recompute_queue
```

`position_cost_basis_state`/`realized_pnl_event`/`realized_pnl_daily_aggregate`는 **내부에서 체결 이벤트로부터 계산한 값**이며, `position_snapshot`(브로커가 보고하는 시점별 값, `source_of_truth='broker'`)과는 별개의 개념이다. 두 값은 서로 대체하지 않고 대사(reconciliation) 대상으로만 비교한다. 상세 계산 의미론과 상태 전이 규칙은 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md)를 따른다.

## 4. 주요 테이블 초안

### 4.1 client

- `client_id` PK
- `name`
- `status`
- `base_currency`
- `created_at`

### 4.2 account

- `account_id` PK
- `client_id` FK
- `environment` enum: `paper`, `live`
- `broker_code`
- `account_masked`
- `status`
- `risk_profile`

### 4.3 strategy

- `strategy_id` PK
- `client_id` FK
- `name`
- `asset_class`
- `status`

### 4.4 config_version

- `config_version_id` PK
- `client_id` FK
- `environment`
- `version_tag`
- `config_json`
- `checksum`
- `activated_at`

### 4.5 decision_context

- `decision_context_id` PK
- `account_id` FK
- `strategy_id` FK
- `config_version_id` FK
- `market_timestamp`
- `feature_snapshot_id`
- `position_snapshot_id`
- `input_bundle_uri`
- `correlation_id`

설명:

- 특정 시점의 의사결정 입력 묶음이다.
- replay의 기준키 역할을 한다.

### 4.6 agent_run

- `agent_run_id` PK
- `decision_context_id` FK
- `agent_type`
- `model_id`
- `prompt_id`
- `temperature`
- `seed`
- `raw_output_uri`
- `structured_output_json`
- `started_at`
- `completed_at`

### 4.7 trade_decision

- `trade_decision_id` PK
- `decision_context_id` FK
- `decision_type` enum: `APPROVE`, `REJECT`, `HOLD`, `WATCH`, `EXIT`, `REDUCE`
- `side` enum: `BUY`, `SELL`, `HOLD`, `EXIT`, `REDUCE`
- `strategy_id`
- `symbol`
- `market`
- `entry_style` enum: `LIMIT`, `MARKET`, `VWAP`, `TWAP`, `NO_ORDER`
- `entry_price`
- `price_band_lower`
- `price_band_upper`
- `quantity`
- `max_order_value`
- `expected_return_bps`
- `expected_downside_bps`
- `net_expected_value_bps`
- `final_trade_score`
- `confidence`
- `minimum_required_edge_bps`
- `regime_label`
- `strategy_fit_score`
- `risk_check_passed`
- `compliance_check_passed`
- `execution_check_passed`
- `failed_rule_codes` jsonb
- `reason_codes` jsonb
- `opposing_evidence` jsonb
- `exit_plan_json`
- `calculation_version`
- `agent_version_json`
- `model_version_json`
- `prompt_version_json`

명시:

- `final_trade_score`는 랭킹과 의사결정 보조용이다.
- `net_expected_value_bps`는 실제 주문 가능성 판단용이다.
- `net_expected_value_bps <= minimum_required_edge_bps`이면 `order_request` 생성 불가다.

### 4.8 order_request

- `order_request_id` PK
- `account_id` FK
- `trade_decision_id` FK
- `client_order_id`
- `idempotency_key`
- `symbol`
- `side`
- `order_type`
- `price`
- `qty`
- `status`
- `status_reason_code`
- `submitted_at`

### 4.9 broker_order

- `broker_order_id` PK
- `order_request_id` FK
- `broker_name`
- `broker_native_order_id`
- `broker_status`
- `request_payload_uri`
- `response_payload_uri`
- `last_synced_at`

### 4.10 fill_event

- `fill_event_id` PK
- `broker_order_id` FK
- `fill_timestamp`
- `fill_price`
- `fill_qty`
- `fill_fee`
- `fill_tax`
- `source_channel`

### 4.11 position_snapshot

- `position_snapshot_id` PK
- `account_id` FK
- `symbol`
- `qty`
- `avg_price`
- `market_price`
- `unrealized_pnl`
- `source_of_truth` enum: `internal`, `broker`, `reconciled`
- `snapshot_at`

### 4.12 reconciliation_run

- `reconciliation_run_id` PK
- `account_id` FK
- `trigger_type`
- `status`
- `mismatch_count`
- `summary_json`
- `started_at`
- `completed_at`

### 4.13 risk_limit_snapshot

- `risk_limit_snapshot_id` PK
- `account_id` FK
- `config_version_id` FK
- `snapshot_at`
- `nav`
- `cash_available`
- `gross_exposure_pct`
- `net_exposure_pct`
- `daily_realized_pnl`
- `daily_unrealized_pnl`
- `daily_loss_used_pct`
- `max_daily_loss_limit_pct`
- `symbol_exposure_json`
- `sector_exposure_json`
- `open_order_exposure_json`
- `drawdown_state`
- `kill_switch_active`
- `blocked_reason_codes` jsonb

### 4.14 guardrail_evaluation

- `guardrail_evaluation_id` PK
- `decision_context_id` FK
- `trade_decision_id` FK nullable
- `order_request_id` FK nullable
- `rule_set_version`
- `overall_passed`
- `evaluated_at`
- `rule_results_jsonb`
- `blocking_rule_codes` jsonb
- `warning_rule_codes` jsonb

### 4.15 order_state_event

- `order_state_event_id` PK
- `order_request_id` FK
- `previous_status`
- `new_status`
- `event_source` enum: `internal`, `broker_rest`, `broker_ws`, `reconciliation`, `operator`
- `event_timestamp`
- `ingested_at`
- `reason_code`
- `raw_event_uri`
- `correlation_id`

### 4.16 decision_state_event

- `decision_state_event_id` PK
- `trade_decision_id` FK
- `previous_state`
- `new_state`
- `event_source`
- `event_timestamp`
- `reason_code`
- `correlation_id`

### 4.17 broker_api_call_log

- `broker_api_call_id` PK
- `broker_name`
- `environment`
- `account_id` nullable
- `correlation_id`
- `endpoint_name`
- `operation_type`
- `request_payload_uri`
- `response_payload_uri`
- `http_status`
- `raw_code`
- `normalized_error_type`
- `retryable`
- `latency_ms`
- `called_at`

### 4.18 market_data_quality_event

- `market_data_quality_event_id` PK
- `symbol`
- `market`
- `source_name`
- `event_type`
- `severity`
- `market_timestamp`
- `ingested_at`
- `delay_ms`
- `observed_value_json`
- `action_taken`
- `correlation_id`

### 4.19 position_cost_basis_state

> **설계 상태**: migration 초안 작성됨(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`, 미실행) — repository/runtime 코드는 아직 없음. 상세 설계는 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md#41-position_cost_basis_state) 참고.

- `account_id` FK, `instrument_id` FK — 복합 PK
- `quantity`
- `average_cost`
- `last_applied_fill_event_id` FK `fill_event`, nullable
- `last_applied_fill_timestamp`
- `recompute_required`
- `recompute_reason`
- `updated_at`

설명:

- 이동평균법으로 계산한 **내부 계산값**이다. `position_snapshot.average_price`(브로커 원장값)와 동일시하지 않는다.
- 완전 청산(`quantity == 0`) 시 `average_cost`를 0으로 리셋한다.

### 4.20 realized_pnl_event

> **설계 상태**: migration 초안 작성됨(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`, 미실행) — repository/runtime 코드는 아직 없음. 상세 설계는 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md#42-realized_pnl_events) 참고.

- `realized_pnl_event_id` PK
- `account_id` FK
- `instrument_id` FK
- `fill_event_id` FK `fill_event`, **UNIQUE, NOT NULL**
- `broker_order_id` FK
- `order_request_id` FK
- `sell_quantity`
- `sell_price`
- `avg_cost_basis_before`
- `fee`
- `tax`
- `fee_tax_source` enum: `reported`, `assumed_zero`
- `realized_pnl_gross`
- `realized_pnl_net`
- `position_quantity_after`
- `computation_run_id` FK
- `superseded_by_event_id` FK `realized_pnl_event`, nullable, self-reference
- `fill_timestamp`
- `created_at`

설명:

- append-only 원장이다. UPDATE/DELETE하지 않는다. 정정은 `superseded_by_event_id`를 채운 보정 행 append로만 처리한다.
- `fill_event_id` UNIQUE 제약이 idempotency의 1차 방어선이다.

### 4.21 realized_pnl_daily_aggregate

> **설계 상태**: migration 초안 작성됨(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`, 미실행) — repository/runtime 코드는 아직 없음. 상세 설계는 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md#43-realized_pnl_daily_aggregates) 참고.

- `account_id`, `instrument_id`, `trade_date` — 복합 PK
- `realized_pnl_net_sum`
- `sell_event_count`
- `computation_run_id`
- `updated_at`

설명:

- `realized_pnl_event`에서 언제든 재생성 가능한 파생 캐시다. 진실의 원천이 아니다.

### 4.22 realized_pnl_computation_run

> **설계 상태**: migration 초안 작성됨(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`, 미실행) — repository/runtime 코드는 아직 없음. 상세 설계는 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md#44-realized_pnl_computation_runs) 참고.

- `computation_run_id` PK
- `run_type` enum: `realtime_incremental`, `backfill_replay`
- `account_id` nullable
- `status` enum: `running`, `completed`, `partial`, `failed`
- `fills_applied`, `fills_skipped_duplicate`, `fills_replayed`, `anomalies_detected`
- `started_at`, `completed_at`
- `summary_json`

설명:

- `fill_sync_run`과 동일한 관측성 패턴이다.

### 4.23 realized_pnl_recompute_queue

> **설계 상태**: migration 초안 작성됨(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`, 미실행) — repository/runtime 코드는 아직 없음. 상세 설계는 [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md#45-realized_pnl_recompute_queue) 참고.

- `recompute_queue_id` PK
- `account_id`, `instrument_id`
- `reason_code` enum: `ledger_write_failed`, `out_of_order_fill_detected`, `anomaly_negative_quantity`, `manual_request`
- `triggering_fill_event_id` nullable
- `requested_at`
- `resolved_at` nullable
- `resolved_by_computation_run_id` nullable FK

설명:

- fill 저장 성공 이후 ledger 갱신이 실패하거나 out-of-order fill이 감지됐을 때, 이를 조용히 넘기지 않고 관측·복구 가능하게 만드는 큐다.

## 5. 감사 로그 규칙

`audit_log`는 최소한 아래를 저장한다.

- actor type: system, operator, agent
- actor id
- action
- target entity
- before json
- after json
- correlation id
- created at

## 6. 재현성 저장 규칙

replay를 위해 다음을 보관한다.

- 원시 시장 데이터 참조
- feature snapshot 버전
- config version
- model version
- prompt version
- agent raw output
- trade decision structured output

## 7. 인덱스 권장

- `order_request(client_order_id)` unique
- `order_request(idempotency_key)` unique where status not in terminal statuses
- `order_request(account_id, status, submitted_at)`
- `broker_order(broker_name, broker_native_order_id)` unique where `broker_native_order_id` is not null
- `fill_event(broker_order_id, fill_timestamp)`
- `fill_event(broker_order_id, broker_fill_id)` unique where `broker_fill_id` is not null
- `decision_context(account_id, market_timestamp)`
- `guardrail_evaluation(decision_context_id)`
- `risk_limit_snapshot(account_id, snapshot_at)`
- `order_state_event(order_request_id, event_timestamp)`
- `decision_state_event(trade_decision_id, event_timestamp)`
- `broker_api_call_log(correlation_id)`
- `market_data_quality_event(symbol, market_timestamp)`
- `audit_log(correlation_id)`
- `position_cost_basis_state(account_id, instrument_id)` unique (복합 PK)
- `realized_pnl_event(fill_event_id)` unique
- `realized_pnl_event(account_id, instrument_id, fill_timestamp)`
- `realized_pnl_daily_aggregate(account_id, instrument_id, trade_date)` unique (복합 PK)
- `realized_pnl_recompute_queue(account_id, instrument_id, resolved_at)`

## 8. Enum 목록

- `environment`: `paper`, `live`
- `order_status`
- `decision_state`
- `decision_type`
- `order_side`
- `order_type`
- `entry_style`
- `event_source`
- `guardrail_action`
- `reconciliation_status`
- `broker_error_type`
- `market_data_quality_severity`

## 9. v1 ERD 결정 사항

- 현재 상태 테이블과 이벤트 테이블을 함께 유지한다.
- 고빈도 tick 원본은 RDB에 직접 모두 저장하지 않고 object storage 또는 시계열 저장소를 사용한다.
- replay bundle은 DB row가 아니라 object storage manifest를 참조한다.
- 실현 손익은 "가변 상태(`position_cost_basis_state`)"와 "불변 원장(`realized_pnl_event`)"과 "파생 집계(`realized_pnl_daily_aggregate`)"를 분리 저장한다. 파생 집계는 원장에서 언제든 재생성 가능해야 하며 진실의 원천이 될 수 없다.
- 브로커가 보고하는 시점별 값(`position_snapshot.average_price`, `source_of_truth='broker'`)과 내부에서 체결 이벤트로부터 계산한 값(`position_cost_basis_state.average_cost`)은 동일시하지 않는다. 두 값은 대사(reconciliation) 대상으로만 비교한다. 상세 설계: [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md).
