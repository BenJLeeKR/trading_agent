CREATE TABLE IF NOT EXISTS trading.operations_day_runs (
    operations_day_run_id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL UNIQUE,
    scheduler_status TEXT NOT NULL DEFAULT 'running',
    is_trading_day BOOLEAN NOT NULL DEFAULT TRUE,
    session_source TEXT,
    market_phase TEXT,
    pre_market_done BOOLEAN NOT NULL DEFAULT FALSE,
    end_of_day_done BOOLEAN NOT NULL DEFAULT FALSE,
    after_hours_mode BOOLEAN NOT NULL DEFAULT FALSE,
    recovery_batch_done BOOLEAN NOT NULL DEFAULT FALSE,
    submit_count INTEGER NOT NULL DEFAULT 0,
    held_position_sell_submit_count INTEGER NOT NULL DEFAULT 0,
    cycles INTEGER NOT NULL DEFAULT 0,
    last_phase_change_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_operations_day_runs_updated_at
    ON trading.operations_day_runs (updated_at DESC);
