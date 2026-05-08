BEGIN;

-- Add broker_account_code to broker_accounts table (nullable, backfill later)
ALTER TABLE trading.broker_accounts
    ADD COLUMN broker_account_code VARCHAR(255);

-- Add account_code to accounts table (nullable, backfill later)
ALTER TABLE trading.accounts
    ADD COLUMN account_code VARCHAR(255);

COMMIT;
