CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_feature_snapshots_natural_key
    ON trading.signal_feature_snapshots (
        instrument_id,
        timeframe,
        snapshot_at,
        feature_set_version
    );
