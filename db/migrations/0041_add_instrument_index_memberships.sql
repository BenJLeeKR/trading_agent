CREATE TABLE IF NOT EXISTS trading.instrument_index_memberships (
    instrument_index_membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id) ON DELETE CASCADE,
    membership_code TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    source_tag TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_instrument_index_memberships_instrument_active
    ON trading.instrument_index_memberships (instrument_id, effective_to, membership_code);

CREATE INDEX IF NOT EXISTS idx_instrument_index_memberships_membership_active
    ON trading.instrument_index_memberships (membership_code, effective_to, instrument_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_index_memberships_open
    ON trading.instrument_index_memberships (instrument_id, membership_code)
    WHERE effective_to IS NULL;

COMMENT ON TABLE trading.instrument_index_memberships IS
    '국내주식 index membership authoritative history. metadata.index_memberships의 후속 정식 승격 테이블.';

COMMENT ON COLUMN trading.instrument_index_memberships.membership_code IS
    '예: KOSPI100, KOSPI200, KOSDAQ50, KOSDAQ150';
