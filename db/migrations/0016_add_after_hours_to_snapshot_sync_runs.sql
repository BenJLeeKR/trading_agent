ALTER TABLE trading.snapshot_sync_runs
  ADD COLUMN after_hours BOOLEAN NOT NULL DEFAULT false;
