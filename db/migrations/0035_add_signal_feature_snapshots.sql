CREATE TABLE IF NOT EXISTS trading.signal_feature_snapshots (
    signal_feature_snapshot_id UUID PRIMARY KEY,
    instrument_id UUID NOT NULL REFERENCES trading.instruments(instrument_id) ON DELETE CASCADE,
    timeframe TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    feature_set_version TEXT NOT NULL,
    bar_count INTEGER NOT NULL CHECK (bar_count > 0),
    sma_5 NUMERIC(20,8) NULL,
    sma_20 NUMERIC(20,8) NULL,
    sma_60 NUMERIC(20,8) NULL,
    price_vs_sma_20_pct NUMERIC(20,8) NULL,
    price_vs_sma_60_pct NUMERIC(20,8) NULL,
    return_1m_pct NUMERIC(20,8) NULL,
    return_3m_pct NUMERIC(20,8) NULL,
    volatility_20d_pct NUMERIC(20,8) NULL,
    atr_14_pct NUMERIC(20,8) NULL,
    rsi_14 NUMERIC(20,8) NULL,
    average_volume_20d NUMERIC(20,8) NULL,
    volume_surge_ratio NUMERIC(20,8) NULL,
    fast_score NUMERIC(20,8) NULL,
    slow_score NUMERIC(20,8) NULL,
    overall_score NUMERIC(20,8) NULL,
    component_scores_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes TEXT[] NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_feature_snapshots_instrument_timeframe_snapshot_at
    ON trading.signal_feature_snapshots (instrument_id, timeframe, snapshot_at DESC);

COMMENT ON TABLE trading.signal_feature_snapshots IS
    'Deterministic signal feature snapshots computed from price history for replayable AI/decision inputs.';

COMMENT ON COLUMN trading.signal_feature_snapshots.component_scores_json IS
    'Per-component fast/slow signal scores before final aggregation.';
