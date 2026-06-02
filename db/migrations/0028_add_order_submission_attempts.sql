-- 0028: Add order_submission_attempts table
-- Records every broker submission attempt (success/rejection/exception)
-- so submission history is never lost.
-- MVP: attempt_number is always 1 (future: use COUNT from DB).

CREATE TABLE IF NOT EXISTS trading.order_submission_attempts (
    attempt_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_request_id        UUID NOT NULL REFERENCES trading.order_requests(order_request_id),
    attempt_number          INTEGER NOT NULL,
    submitted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    broker_name             VARCHAR(64),
    accepted                BOOLEAN NOT NULL,
    broker_native_order_id  VARCHAR(128),
    broker_status           VARCHAR(64),
    raw_code                VARCHAR(128),
    raw_message             TEXT,
    error_type              VARCHAR(64),
    retryable               BOOLEAN,
    http_status             INTEGER,
    request_payload_uri     TEXT,
    response_payload_uri    TEXT,
    duration_ms             INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_submission_attempts_order
    ON trading.order_submission_attempts(order_request_id, attempt_number);
