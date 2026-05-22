-- 0021_add_pipeline_stop_fields.sql
-- purpose: track where in the submit pipeline a trade_decision stopped
ALTER TABLE trading.trade_decisions
    ADD COLUMN pipeline_stop_phase VARCHAR(64),
    ADD COLUMN pipeline_stop_reason TEXT,
    ADD COLUMN pipeline_stopped_at TIMESTAMPTZ;
