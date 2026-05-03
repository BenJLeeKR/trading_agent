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
```

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
