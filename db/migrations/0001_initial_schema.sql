BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS trading;

CREATE TABLE IF NOT EXISTS trading.clients (
    client_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'KRW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_clients_status
        CHECK (status IN ('active', 'inactive', 'suspended'))
);

CREATE TABLE IF NOT EXISTS trading.broker_accounts (
    broker_account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_name VARCHAR(64) NOT NULL,
    account_ref VARCHAR(128) NOT NULL,
    environment VARCHAR(16) NOT NULL,
    credential_ref VARCHAR(255) NOT NULL,
    base_url VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_broker_accounts_ref UNIQUE (broker_name, account_ref, environment),
    CONSTRAINT ck_broker_accounts_environment
        CHECK (environment IN ('paper', 'live')),
    CONSTRAINT ck_broker_accounts_status
        CHECK (status IN ('active', 'inactive', 'disabled'))
);

CREATE TABLE IF NOT EXISTS trading.accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES trading.clients (client_id),
    broker_account_id UUID NOT NULL REFERENCES trading.broker_accounts (broker_account_id),
    environment VARCHAR(16) NOT NULL,
    account_alias VARCHAR(128) NOT NULL,
    account_masked VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    risk_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_accounts_alias UNIQUE (client_id, account_alias, environment),
    CONSTRAINT ck_accounts_environment
        CHECK (environment IN ('paper', 'live')),
    CONSTRAINT ck_accounts_status
        CHECK (status IN ('active', 'inactive', 'blocked'))
);

CREATE TABLE IF NOT EXISTS trading.strategies (
    strategy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES trading.clients (client_id),
    strategy_code VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    asset_class VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategies_code UNIQUE (client_id, strategy_code),
    CONSTRAINT ck_strategies_status
        CHECK (status IN ('draft', 'active', 'inactive', 'retired'))
);

CREATE TABLE IF NOT EXISTS trading.strategy_versions (
    strategy_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id UUID NOT NULL REFERENCES trading.strategies (strategy_id),
    version_tag VARCHAR(64) NOT NULL,
    artifact_uri TEXT,
    checksum VARCHAR(128),
    changelog TEXT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    CONSTRAINT uq_strategy_versions UNIQUE (strategy_id, version_tag)
);

CREATE TABLE IF NOT EXISTS trading.config_versions (
    config_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES trading.clients (client_id),
    environment VARCHAR(16) NOT NULL,
    version_tag VARCHAR(64) NOT NULL,
    config_json JSONB NOT NULL,
    checksum VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    activated_by VARCHAR(128),
    CONSTRAINT uq_config_versions UNIQUE (client_id, environment, version_tag),
    CONSTRAINT ck_config_versions_environment
        CHECK (environment IN ('paper', 'live'))
);

CREATE TABLE IF NOT EXISTS trading.trading_sessions (
    trading_session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    session_date DATE NOT NULL,
    market_code VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_trading_sessions UNIQUE (account_id, session_date, market_code),
    CONSTRAINT ck_trading_sessions_status
        CHECK (status IN ('scheduled', 'open', 'closed', 'halted'))
);

CREATE TABLE IF NOT EXISTS trading.instruments (
    instrument_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(64) NOT NULL,
    market_code VARCHAR(32) NOT NULL,
    exchange_code VARCHAR(32) NOT NULL,
    market_segment VARCHAR(32) NOT NULL,
    asset_class VARCHAR(32) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'KRW',
    name VARCHAR(255) NOT NULL,
    tick_size NUMERIC(20, 8),
    lot_size NUMERIC(20, 8),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_instruments UNIQUE (symbol, market_code)
);

CREATE TABLE IF NOT EXISTS trading.market_data_snapshots (
    market_data_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    snapshot_at TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(64) NOT NULL,
    quality_status VARCHAR(32) NOT NULL,
    last_price NUMERIC(20, 8),
    bid_price NUMERIC(20, 8),
    ask_price NUMERIC(20, 8),
    volume NUMERIC(24, 8),
    payload_uri TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_market_data_quality_status
        CHECK (quality_status IN ('ok', 'degraded', 'stale', 'rejected'))
);

CREATE TABLE IF NOT EXISTS trading.feature_snapshots (
    feature_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID REFERENCES trading.instruments (instrument_id),
    strategy_id UUID REFERENCES trading.strategies (strategy_id),
    feature_set_name VARCHAR(128) NOT NULL,
    feature_version VARCHAR(64) NOT NULL,
    market_timestamp TIMESTAMPTZ NOT NULL,
    features_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading.model_registry (
    model_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_key VARCHAR(128) NOT NULL UNIQUE,
    provider VARCHAR(64) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading.prompt_registry (
    prompt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key VARCHAR(128) NOT NULL UNIQUE,
    version_tag VARCHAR(64) NOT NULL,
    prompt_template_uri TEXT NOT NULL,
    checksum VARCHAR(128),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_prompt_registry_key_version UNIQUE (prompt_key, version_tag)
);

CREATE TABLE IF NOT EXISTS trading.position_snapshots (
    position_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    quantity NUMERIC(24, 8) NOT NULL,
    average_price NUMERIC(20, 8) NOT NULL,
    market_price NUMERIC(20, 8),
    unrealized_pnl NUMERIC(20, 8),
    source_of_truth VARCHAR(32) NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_position_snapshots_source_of_truth
        CHECK (source_of_truth IN ('internal', 'broker', 'reconciled'))
);

CREATE TABLE IF NOT EXISTS trading.cash_balance_snapshots (
    cash_balance_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    currency CHAR(3) NOT NULL DEFAULT 'KRW',
    available_cash NUMERIC(20, 8) NOT NULL,
    settled_cash NUMERIC(20, 8),
    unsettled_cash NUMERIC(20, 8),
    source_of_truth VARCHAR(32) NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_cash_balance_source_of_truth
        CHECK (source_of_truth IN ('internal', 'broker', 'reconciled'))
);

CREATE TABLE IF NOT EXISTS trading.decision_contexts (
    decision_context_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    strategy_id UUID NOT NULL REFERENCES trading.strategies (strategy_id),
    strategy_version_id UUID REFERENCES trading.strategy_versions (strategy_version_id),
    config_version_id UUID NOT NULL REFERENCES trading.config_versions (config_version_id),
    trading_session_id UUID REFERENCES trading.trading_sessions (trading_session_id),
    feature_snapshot_id UUID REFERENCES trading.feature_snapshots (feature_snapshot_id),
    position_snapshot_id UUID REFERENCES trading.position_snapshots (position_snapshot_id),
    cash_balance_snapshot_id UUID REFERENCES trading.cash_balance_snapshots (cash_balance_snapshot_id),
    market_timestamp TIMESTAMPTZ NOT NULL,
    input_bundle_uri TEXT,
    correlation_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_decision_context_correlation UNIQUE (correlation_id)
);

CREATE TABLE IF NOT EXISTS trading.agent_runs (
    agent_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id UUID NOT NULL REFERENCES trading.decision_contexts (decision_context_id),
    agent_type VARCHAR(64) NOT NULL,
    model_id UUID REFERENCES trading.model_registry (model_id),
    prompt_id UUID REFERENCES trading.prompt_registry (prompt_id),
    temperature NUMERIC(8, 4),
    seed BIGINT,
    raw_output_uri TEXT,
    structured_output_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_runs_status
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS trading.risk_decisions (
    risk_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id UUID NOT NULL UNIQUE REFERENCES trading.decision_contexts (decision_context_id),
    agent_run_id UUID REFERENCES trading.agent_runs (agent_run_id),
    decision VARCHAR(32) NOT NULL,
    risk_score NUMERIC(8, 4),
    max_position_size_pct NUMERIC(8, 4),
    max_loss_limit_pct NUMERIC(8, 4),
    rationale_summary TEXT,
    decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_risk_decisions_decision
        CHECK (decision IN ('allow', 'reduce', 'deny', 'exit'))
);

CREATE TABLE IF NOT EXISTS trading.compliance_decisions (
    compliance_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id UUID NOT NULL UNIQUE REFERENCES trading.decision_contexts (decision_context_id),
    agent_run_id UUID REFERENCES trading.agent_runs (agent_run_id),
    decision VARCHAR(32) NOT NULL,
    violation_count INTEGER NOT NULL DEFAULT 0,
    rationale_summary TEXT,
    decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_compliance_decisions_decision
        CHECK (decision IN ('allow', 'review', 'deny'))
);

CREATE TABLE IF NOT EXISTS trading.trade_decisions (
    trade_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id UUID NOT NULL UNIQUE REFERENCES trading.decision_contexts (decision_context_id),
    agent_run_id UUID REFERENCES trading.agent_runs (agent_run_id),
    instrument_id UUID REFERENCES trading.instruments (instrument_id),
    decision VARCHAR(32) NOT NULL,
    target_quantity NUMERIC(24, 8),
    target_notional NUMERIC(20, 8),
    limit_price NUMERIC(20, 8),
    confidence NUMERIC(8, 4),
    rationale_summary TEXT,
    decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_trade_decisions_decision
        CHECK (decision IN ('buy', 'sell', 'hold', 'reduce', 'exit'))
);

CREATE TABLE IF NOT EXISTS trading.order_requests (
    order_request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    trade_decision_id UUID REFERENCES trading.trade_decisions (trade_decision_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    client_order_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    correlation_id VARCHAR(128) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(32) NOT NULL,
    time_in_force VARCHAR(16) NOT NULL DEFAULT 'day',
    requested_price NUMERIC(20, 8),
    requested_quantity NUMERIC(24, 8) NOT NULL,
    status VARCHAR(32) NOT NULL,
    status_reason_code VARCHAR(64),
    status_reason_message TEXT,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_order_requests_client_order_id UNIQUE (client_order_id),
    CONSTRAINT uq_order_requests_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT ck_order_requests_side
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_order_requests_type
        CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
    CONSTRAINT ck_order_requests_tif
        CHECK (time_in_force IN ('day', 'ioc', 'fok')),
    CONSTRAINT ck_order_requests_status
        CHECK (status IN (
            'draft',
            'validated',
            'pending_submit',
            'submitted',
            'acknowledged',
            'partially_filled',
            'filled',
            'cancel_pending',
            'cancelled',
            'rejected',
            'expired',
            'reconcile_required'
        )),
    CONSTRAINT ck_order_requests_quantity
        CHECK (requested_quantity > 0)
);

CREATE TABLE IF NOT EXISTS trading.broker_orders (
    broker_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_request_id UUID NOT NULL REFERENCES trading.order_requests (order_request_id),
    broker_name VARCHAR(64) NOT NULL,
    broker_native_order_id VARCHAR(128),
    broker_status VARCHAR(64) NOT NULL,
    request_payload_uri TEXT,
    response_payload_uri TEXT,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_broker_orders_native UNIQUE (broker_name, broker_native_order_id)
);

CREATE TABLE IF NOT EXISTS trading.fill_events (
    fill_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_order_id UUID NOT NULL REFERENCES trading.broker_orders (broker_order_id),
    broker_fill_id VARCHAR(128),
    fill_timestamp TIMESTAMPTZ NOT NULL,
    fill_price NUMERIC(20, 8) NOT NULL,
    fill_quantity NUMERIC(24, 8) NOT NULL,
    fill_fee NUMERIC(20, 8),
    fill_tax NUMERIC(20, 8),
    source_channel VARCHAR(32) NOT NULL,
    raw_payload_uri TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fill_events_native UNIQUE (broker_order_id, broker_fill_id),
    CONSTRAINT ck_fill_events_source_channel
        CHECK (source_channel IN ('websocket', 'rest_poll', 'backfill', 'manual')),
    CONSTRAINT ck_fill_events_quantity
        CHECK (fill_quantity > 0)
);

CREATE TABLE IF NOT EXISTS trading.reconciliation_runs (
    reconciliation_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    trigger_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    mismatch_count INTEGER NOT NULL DEFAULT 0,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_reconciliation_runs_trigger
        CHECK (trigger_type IN ('schedule', 'submit_timeout', 'ws_disconnect', 'manual', 'eod')),
    CONSTRAINT ck_reconciliation_runs_status
        CHECK (status IN ('started', 'completed', 'failed', 'halted'))
);

CREATE TABLE IF NOT EXISTS trading.reconciliation_order_links (
    reconciliation_run_id UUID NOT NULL REFERENCES trading.reconciliation_runs (reconciliation_run_id),
    order_request_id UUID NOT NULL REFERENCES trading.order_requests (order_request_id),
    mismatch_type VARCHAR(64) NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (reconciliation_run_id, order_request_id)
);

CREATE TABLE IF NOT EXISTS trading.reconciliation_position_links (
    reconciliation_run_id UUID NOT NULL REFERENCES trading.reconciliation_runs (reconciliation_run_id),
    position_snapshot_id UUID NOT NULL REFERENCES trading.position_snapshots (position_snapshot_id),
    mismatch_type VARCHAR(64) NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (reconciliation_run_id, position_snapshot_id)
);

CREATE TABLE IF NOT EXISTS trading.replay_bundles (
    replay_bundle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id UUID NOT NULL UNIQUE REFERENCES trading.decision_contexts (decision_context_id),
    bundle_uri TEXT NOT NULL,
    checksum VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading.audit_logs (
    audit_log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    action VARCHAR(128) NOT NULL,
    target_entity_type VARCHAR(64) NOT NULL,
    target_entity_id VARCHAR(128) NOT NULL,
    before_json JSONB,
    after_json JSONB,
    correlation_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_audit_logs_actor_type
        CHECK (actor_type IN ('system', 'operator', 'agent'))
);

CREATE INDEX IF NOT EXISTS idx_accounts_client_status
    ON trading.accounts (client_id, status);

CREATE INDEX IF NOT EXISTS idx_trading_sessions_account_date
    ON trading.trading_sessions (account_id, session_date DESC);

CREATE INDEX IF NOT EXISTS idx_market_data_snapshots_instrument_time
    ON trading.market_data_snapshots (instrument_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_strategy_time
    ON trading.feature_snapshots (strategy_id, market_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_position_snapshots_account_time
    ON trading.position_snapshots (account_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_cash_balance_snapshots_account_time
    ON trading.cash_balance_snapshots (account_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_contexts_account_market_time
    ON trading.decision_contexts (account_id, market_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_decision_context
    ON trading.agent_runs (decision_context_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_requests_account_status_submitted
    ON trading.order_requests (account_id, status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_requests_trade_decision
    ON trading.order_requests (trade_decision_id);

CREATE INDEX IF NOT EXISTS idx_broker_orders_order_request
    ON trading.broker_orders (order_request_id);

CREATE INDEX IF NOT EXISTS idx_fill_events_broker_order_time
    ON trading.fill_events (broker_order_id, fill_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_account_started
    ON trading.reconciliation_runs (account_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation_id
    ON trading.audit_logs (correlation_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_target
    ON trading.audit_logs (target_entity_type, target_entity_id, created_at DESC);

COMMIT;
