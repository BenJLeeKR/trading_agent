ALTER TABLE trading.signal_feature_snapshots
    ADD COLUMN IF NOT EXISTS average_turnover_20d NUMERIC(20,8) NULL,
    ADD COLUMN IF NOT EXISTS turnover_surge_ratio NUMERIC(20,8) NULL;

COMMENT ON COLUMN trading.signal_feature_snapshots.average_turnover_20d IS
    '최근 20일 평균 거래대금.';

COMMENT ON COLUMN trading.signal_feature_snapshots.turnover_surge_ratio IS
    '당일 거래대금 / 최근 20일 평균 거래대금 비율.';
