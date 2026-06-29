BEGIN;

ALTER TABLE trading.risk_limit_snapshots
    ADD COLUMN IF NOT EXISTS var_confidence_level NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS var_horizon_days INTEGER,
    ADD COLUMN IF NOT EXISTS var_lookback_days INTEGER,
    ADD COLUMN IF NOT EXISTS portfolio_var_1d NUMERIC(24, 8),
    ADD COLUMN IF NOT EXISTS portfolio_var_1d_adjusted NUMERIC(24, 8),
    ADD COLUMN IF NOT EXISTS largest_var_symbol VARCHAR(32),
    ADD COLUMN IF NOT EXISTS largest_var_contribution_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS concentration_penalty_pct NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS var_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS var_reason_codes TEXT[],
    ADD COLUMN IF NOT EXISTS symbol_var_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS symbol_marginal_contribution_json JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN trading.risk_limit_snapshots.var_confidence_level IS
    'Phase 1 deterministic VaR confidence level (e.g. 0.95).';
COMMENT ON COLUMN trading.risk_limit_snapshots.var_horizon_days IS
    'Phase 1 deterministic VaR horizon in trading days.';
COMMENT ON COLUMN trading.risk_limit_snapshots.var_lookback_days IS
    'Phase 1 deterministic VaR lookback window in trading days.';
COMMENT ON COLUMN trading.risk_limit_snapshots.portfolio_var_1d IS
    'Base one-day portfolio VaR before concentration penalty.';
COMMENT ON COLUMN trading.risk_limit_snapshots.portfolio_var_1d_adjusted IS
    'Adjusted one-day portfolio VaR after concentration penalty.';
COMMENT ON COLUMN trading.risk_limit_snapshots.largest_var_symbol IS
    'Symbol contributing the largest single-name VaR share.';
COMMENT ON COLUMN trading.risk_limit_snapshots.largest_var_contribution_pct IS
    'Largest symbol VaR contribution as percentage of base portfolio VaR.';
COMMENT ON COLUMN trading.risk_limit_snapshots.concentration_penalty_pct IS
    'Account-level concentration penalty applied to adjusted VaR.';
COMMENT ON COLUMN trading.risk_limit_snapshots.var_status IS
    'Deterministic VaR calculation status such as ready or insufficient_data.';
COMMENT ON COLUMN trading.risk_limit_snapshots.var_reason_codes IS
    'Reason codes explaining VaR unavailable or degraded states.';
COMMENT ON COLUMN trading.risk_limit_snapshots.symbol_var_json IS
    'JSONB map of symbol -> absolute Phase 1 one-day VaR.';
COMMENT ON COLUMN trading.risk_limit_snapshots.symbol_marginal_contribution_json IS
    'JSONB map of symbol -> approximate marginal VaR contribution share.';

COMMIT;
