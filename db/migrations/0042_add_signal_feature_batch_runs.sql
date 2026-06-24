CREATE TABLE IF NOT EXISTS trading.signal_feature_batch_runs (
    signal_feature_batch_run_id UUID PRIMARY KEY,
    business_date DATE NOT NULL,
    universe_freeze_run_id UUID NULL
        REFERENCES trading.universe_freeze_runs(universe_freeze_run_id) ON DELETE SET NULL,
    trigger_type TEXT NOT NULL DEFAULT 'scheduler',
    timeframe TEXT NOT NULL DEFAULT '1d',
    feature_set_version TEXT NOT NULL,
    input_uri TEXT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    target_count INTEGER NOT NULL DEFAULT 0 CHECK (target_count >= 0),
    fetch_success_count INTEGER NOT NULL DEFAULT 0 CHECK (fetch_success_count >= 0),
    fetch_error_count INTEGER NOT NULL DEFAULT 0 CHECK (fetch_error_count >= 0),
    persist_success_count INTEGER NOT NULL DEFAULT 0 CHECK (persist_success_count >= 0),
    persist_error_count INTEGER NOT NULL DEFAULT 0 CHECK (persist_error_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    final_missing_count INTEGER NOT NULL DEFAULT 0 CHECK (final_missing_count >= 0),
    status TEXT NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_feature_batch_runs_business_date
    ON trading.signal_feature_batch_runs (business_date DESC, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_feature_batch_runs_freeze_run_id
    ON trading.signal_feature_batch_runs (universe_freeze_run_id);

CREATE TABLE IF NOT EXISTS trading.signal_feature_batch_run_items (
    signal_feature_batch_run_item_id UUID PRIMARY KEY,
    signal_feature_batch_run_id UUID NOT NULL
        REFERENCES trading.signal_feature_batch_runs(signal_feature_batch_run_id) ON DELETE CASCADE,
    instrument_id UUID NULL
        REFERENCES trading.instruments(instrument_id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    market_code TEXT NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d',
    feature_set_version TEXT NOT NULL,
    status TEXT NOT NULL,
    signal_feature_snapshot_id UUID NULL
        REFERENCES trading.signal_feature_snapshots(signal_feature_snapshot_id) ON DELETE SET NULL,
    snapshot_at TIMESTAMPTZ NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_feature_batch_run_items_run_symbol_timeframe
    ON trading.signal_feature_batch_run_items (signal_feature_batch_run_id, symbol, market_code, timeframe);

CREATE INDEX IF NOT EXISTS idx_signal_feature_batch_run_items_run_status
    ON trading.signal_feature_batch_run_items (signal_feature_batch_run_id, status, symbol);

COMMENT ON TABLE trading.signal_feature_batch_runs IS
    'signal feature 장후 배치 1회 실행 메타데이터. universe freeze와 연결된다.';

COMMENT ON TABLE trading.signal_feature_batch_run_items IS
    'signal feature 배치 내 종목별 persist/error/skipped 결과.';
