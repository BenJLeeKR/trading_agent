ALTER TABLE trading.decision_contexts
    ADD COLUMN IF NOT EXISTS signal_feature_snapshot_id UUID
    REFERENCES trading.signal_feature_snapshots(signal_feature_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_decision_contexts_signal_feature_snapshot_id
    ON trading.decision_contexts (signal_feature_snapshot_id);
