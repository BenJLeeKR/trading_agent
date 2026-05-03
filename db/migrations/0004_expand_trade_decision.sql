BEGIN;

-- ============================================================================
-- Migration 0004: Expand trade_decisions table (Milestone 5)
--
-- Backward-compatible: all new columns are added via ALTER TABLE ADD COLUMN
-- with DEFAULT or nullable, so existing data is preserved.
--
-- P0 fields: core decision fields (NOT NULL or have sensible defaults)
-- P1 fields: extended analysis fields (all nullable, DEFAULT NULL)
-- ============================================================================

-- P0: Core decision fields
ALTER TABLE trading.trade_decisions
    ADD COLUMN IF NOT EXISTS decision_type VARCHAR(32) NOT NULL DEFAULT 'approve',
    ADD COLUMN IF NOT EXISTS side VARCHAR(8) NOT NULL DEFAULT 'buy',
    ADD COLUMN IF NOT EXISTS strategy_id UUID REFERENCES trading.strategies (strategy_id),
    ADD COLUMN IF NOT EXISTS symbol VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS market VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS entry_style VARCHAR(16) NOT NULL DEFAULT 'limit',
    ADD COLUMN IF NOT EXISTS entry_price NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS quantity NUMERIC(24, 8),
    ADD COLUMN IF NOT EXISTS max_order_value NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS price_band_lower NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS price_band_upper NUMERIC(20, 8);

-- P1: Extended analysis fields (all nullable)
ALTER TABLE trading.trade_decisions
    ADD COLUMN IF NOT EXISTS expected_return_bps NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS expected_downside_bps NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS net_expected_value_bps NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS final_trade_score NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS minimum_required_edge_bps NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS regime_label VARCHAR(64),
    ADD COLUMN IF NOT EXISTS strategy_fit_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS risk_check_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS compliance_check_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS execution_check_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS failed_rule_codes JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS reason_codes JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS opposing_evidence JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS exit_plan_json JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS agent_version_json JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS model_version_json JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS prompt_version_json JSONB DEFAULT '{}'::jsonb;

-- New indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_trade_decisions_decision_type
    ON trading.trade_decisions (decision_type);

CREATE INDEX IF NOT EXISTS idx_trade_decisions_strategy_symbol
    ON trading.trade_decisions (strategy_id, symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_decisions_side
    ON trading.trade_decisions (side);

COMMIT;
