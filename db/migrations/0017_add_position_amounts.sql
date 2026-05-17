-- 0017: Add purchase_amount (pchs_amt) and evaluation_amount (evlu_amt) to position_snapshots
--
-- KIS inquire-balance API returns pchs_amt (매입금액) and evlu_amt (평가금액)
-- per-position fields.  These were previously ignored by the snapshot pipeline.
-- This migration adds the DB columns so that the values can be stored and
-- surfaced via the API and UI.

ALTER TABLE trading.position_snapshots
  ADD COLUMN purchase_amount NUMERIC(20,8),
  ADD COLUMN evaluation_amount NUMERIC(20,8);
