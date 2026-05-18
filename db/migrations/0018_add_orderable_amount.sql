-- Add orderable_amount column to cash_balance_snapshots
-- KIS ord_psbl_amt (주문가능금액) — actual orderable cash from broker

ALTER TABLE trading.cash_balance_snapshots
    ADD COLUMN orderable_amount NUMERIC(30, 6);
