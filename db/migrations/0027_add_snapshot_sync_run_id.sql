-- 0027: Add snapshot_sync_run_id FK to position_snapshots and cash_balance_snapshots
-- Allows exact same-run alignment of positions and cash balance snapshots.
-- Nullable for backward compatibility (existing rows remain null).

ALTER TABLE trading.position_snapshots
    ADD COLUMN snapshot_sync_run_id UUID REFERENCES trading.snapshot_sync_runs(snapshot_sync_run_id);

ALTER TABLE trading.cash_balance_snapshots
    ADD COLUMN snapshot_sync_run_id UUID REFERENCES trading.snapshot_sync_runs(snapshot_sync_run_id);

-- Index for efficient lookup by sync run
CREATE INDEX idx_position_snapshots_sync_run_id
    ON trading.position_snapshots (snapshot_sync_run_id);

CREATE INDEX idx_cash_balance_snapshots_sync_run_id
    ON trading.cash_balance_snapshots (snapshot_sync_run_id);
