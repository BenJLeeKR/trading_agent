BEGIN;

CREATE TABLE IF NOT EXISTS trading.snapshot_sync_runs (
    snapshot_sync_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type VARCHAR(32) NOT NULL,
    scope VARCHAR(32) NOT NULL,
    env_filter VARCHAR(16),
    status_filter VARCHAR(64),
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    total_accounts INTEGER NOT NULL DEFAULT 0,
    succeeded_accounts INTEGER NOT NULL DEFAULT 0,
    partial_accounts INTEGER NOT NULL DEFAULT 0,
    failed_accounts INTEGER NOT NULL DEFAULT 0,
    skipped_accounts INTEGER NOT NULL DEFAULT 0,
    positions_synced_total INTEGER NOT NULL DEFAULT 0,
    positions_skipped_total INTEGER NOT NULL DEFAULT 0,
    cash_synced_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    summary_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_snapshot_sync_runs_started_at
    ON trading.snapshot_sync_runs (started_at DESC);
CREATE INDEX idx_snapshot_sync_runs_status
    ON trading.snapshot_sync_runs (status);
CREATE INDEX idx_snapshot_sync_runs_trigger_type
    ON trading.snapshot_sync_runs (trigger_type);

COMMIT;
