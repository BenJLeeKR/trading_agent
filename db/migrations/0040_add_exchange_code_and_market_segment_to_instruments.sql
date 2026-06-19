ALTER TABLE trading.instruments
    ADD COLUMN IF NOT EXISTS exchange_code TEXT NULL,
    ADD COLUMN IF NOT EXISTS market_segment TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_instruments_exchange_code
    ON trading.instruments (exchange_code);

CREATE INDEX IF NOT EXISTS idx_instruments_market_segment
    ON trading.instruments (market_segment);

COMMENT ON COLUMN trading.instruments.exchange_code IS
    'Canonical exchange code. Korean equities use KRX while market_code may remain legacy or segment-specific during migration.';

COMMENT ON COLUMN trading.instruments.market_segment IS
    'Canonical market segment for Korean equities, for example KOSPI or KOSDAQ.';
