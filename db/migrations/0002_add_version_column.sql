BEGIN;

-- Add optimistic locking version column to order_requests.
-- Existing rows get version = 1.
ALTER TABLE trading.order_requests
    ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

COMMIT;
