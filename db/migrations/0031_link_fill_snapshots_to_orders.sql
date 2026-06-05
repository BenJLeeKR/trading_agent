ALTER TABLE trading.broker_fill_snapshots
    ADD COLUMN IF NOT EXISTS order_request_id UUID
        REFERENCES trading.order_requests (order_request_id);

CREATE INDEX IF NOT EXISTS idx_broker_fill_snapshots_order_request
    ON trading.broker_fill_snapshots (order_request_id, order_date DESC, fill_timestamp DESC);
