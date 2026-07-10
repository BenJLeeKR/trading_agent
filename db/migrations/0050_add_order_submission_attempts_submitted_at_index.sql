BEGIN;
CREATE INDEX IF NOT EXISTS idx_submission_attempts_submitted_at
    ON trading.order_submission_attempts (submitted_at DESC);
COMMIT;
