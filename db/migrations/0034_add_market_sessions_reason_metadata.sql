ALTER TABLE trading.market_sessions
    ADD COLUMN IF NOT EXISTS reason_metadata JSONB NULL;

COMMENT ON COLUMN trading.market_sessions.reason_metadata IS
    'Structured evidence for market session reason_code/reason (076/163/fallback inputs).';
