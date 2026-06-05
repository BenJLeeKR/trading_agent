BEGIN;

ALTER TABLE trading.market_sessions
    ADD COLUMN IF NOT EXISTS reason_code VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS idx_market_sessions_reason_code
    ON trading.market_sessions (reason_code);

COMMENT ON COLUMN trading.market_sessions.reason_code IS
    '구조화된 session 판정 코드 (예: COMBINED_076_NON_TRADING, COMBINED_163_SAFE_MODE, FALLBACK_WEEKEND)';

COMMIT;
