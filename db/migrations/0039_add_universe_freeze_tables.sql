CREATE TABLE IF NOT EXISTS trading.universe_freeze_runs (
    universe_freeze_run_id UUID PRIMARY KEY,
    business_date DATE NOT NULL,
    freeze_purpose TEXT NOT NULL,
    freeze_sequence INTEGER NOT NULL CHECK (freeze_sequence > 0),
    frozen_at TIMESTAMPTZ NOT NULL,
    selection_version TEXT NOT NULL,
    selection_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_count INTEGER NOT NULL DEFAULT 0 CHECK (target_count >= 0),
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_universe_freeze_runs_business_date_purpose_sequence
    ON trading.universe_freeze_runs (business_date, freeze_purpose, freeze_sequence);

CREATE INDEX IF NOT EXISTS idx_universe_freeze_runs_purpose_business_date
    ON trading.universe_freeze_runs (freeze_purpose, business_date DESC, frozen_at DESC);

CREATE TABLE IF NOT EXISTS trading.universe_freeze_run_items (
    universe_freeze_run_item_id UUID PRIMARY KEY,
    universe_freeze_run_id UUID NOT NULL
        REFERENCES trading.universe_freeze_runs(universe_freeze_run_id) ON DELETE CASCADE,
    instrument_id UUID NOT NULL
        REFERENCES trading.instruments(instrument_id),
    symbol TEXT NOT NULL,
    market_code TEXT NOT NULL,
    source_type TEXT NOT NULL,
    inclusion_reason TEXT NOT NULL,
    priority_score NUMERIC(20,8) NULL,
    rank INTEGER NULL CHECK (rank IS NULL OR rank > 0),
    cap_bucket TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_universe_freeze_run_items_run_instrument
    ON trading.universe_freeze_run_items (universe_freeze_run_id, instrument_id);

CREATE INDEX IF NOT EXISTS idx_universe_freeze_run_items_run_rank
    ON trading.universe_freeze_run_items (universe_freeze_run_id, rank ASC, symbol ASC);

CREATE INDEX IF NOT EXISTS idx_universe_freeze_run_items_symbol_created_at
    ON trading.universe_freeze_run_items (symbol, created_at DESC);

COMMENT ON TABLE trading.universe_freeze_runs IS
    'Frozen trading-universe run metadata used as authoritative target set for replayable batch execution.';

COMMENT ON TABLE trading.universe_freeze_run_items IS
    'Instrument rows materialised under one frozen trading-universe run.';
