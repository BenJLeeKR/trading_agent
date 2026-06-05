CREATE TABLE IF NOT EXISTS trading.fill_sync_runs (
    fill_sync_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type VARCHAR(32) NOT NULL,
    scope VARCHAR(32) NOT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    total_accounts INTEGER NOT NULL DEFAULT 0,
    succeeded_accounts INTEGER NOT NULL DEFAULT 0,
    partial_accounts INTEGER NOT NULL DEFAULT 0,
    failed_accounts INTEGER NOT NULL DEFAULT 0,
    skipped_accounts INTEGER NOT NULL DEFAULT 0,
    fills_synced_total INTEGER NOT NULL DEFAULT 0,
    fills_skipped_total INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    env_filter VARCHAR(16),
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_fill_sync_runs_trigger
        CHECK (trigger_type IN ('manual', 'scheduler')),
    CONSTRAINT ck_fill_sync_runs_scope
        CHECK (scope IN ('single', 'all')),
    CONSTRAINT ck_fill_sync_runs_status
        CHECK (status IN ('running', 'completed', 'partial', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_fill_sync_runs_started_at
    ON trading.fill_sync_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_fill_sync_runs_status
    ON trading.fill_sync_runs (status);

CREATE TABLE IF NOT EXISTS trading.broker_fill_snapshots (
    broker_fill_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fill_sync_run_id UUID REFERENCES trading.fill_sync_runs (fill_sync_run_id),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    broker_name VARCHAR(64) NOT NULL,
    broker_native_order_id VARCHAR(128) NOT NULL,
    broker_fill_id VARCHAR(128),
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_date DATE NOT NULL,
    order_status_code VARCHAR(32),
    cancel_yn VARCHAR(8),
    ordered_quantity NUMERIC(24, 8),
    filled_quantity NUMERIC(24, 8) NOT NULL,
    fill_price NUMERIC(20, 8) NOT NULL,
    order_time VARCHAR(16),
    fill_time VARCHAR(16),
    fill_timestamp TIMESTAMPTZ,
    dedupe_key VARCHAR(255) NOT NULL,
    raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_broker_fill_snapshots_dedupe UNIQUE (dedupe_key),
    CONSTRAINT ck_broker_fill_snapshots_side
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_broker_fill_snapshots_filled_quantity
        CHECK (filled_quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_broker_fill_snapshots_account_date
    ON trading.broker_fill_snapshots (account_id, order_date DESC, fill_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_broker_fill_snapshots_symbol
    ON trading.broker_fill_snapshots (symbol, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_broker_fill_snapshots_run_id
    ON trading.broker_fill_snapshots (fill_sync_run_id);
