-- Migration 0012: Add KIS output2 account-level summary fields
--
-- KIS inquire-balance output2 (예수금 총괄) contains three account-level
-- summary fields that were previously unmapped:
--   tot_evlu_amt        → total_asset         (총평가금액)
--   prvs_rcdl_excc_amt  → settlement_amount   (가수도정산금액, D+2 예수금 기준)
--   evlu_pfls_smtl_amt  → total_unrealized_pnl (평가손익합계금액)
--
-- All columns are nullable + additive only.
-- Existing rows remain NULL; values are populated on subsequent snapshot syncs.
-- No backfill of historical data is performed.

ALTER TABLE trading.cash_balance_snapshots
    ADD COLUMN total_asset NUMERIC(20,4),
    ADD COLUMN settlement_amount NUMERIC(20,4),
    ADD COLUMN total_unrealized_pnl NUMERIC(20,4);
