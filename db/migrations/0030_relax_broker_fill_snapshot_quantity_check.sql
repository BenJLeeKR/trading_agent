ALTER TABLE trading.broker_fill_snapshots
    DROP CONSTRAINT IF EXISTS ck_broker_fill_snapshots_filled_quantity;

ALTER TABLE trading.broker_fill_snapshots
    ADD CONSTRAINT ck_broker_fill_snapshots_filled_quantity
        CHECK (filled_quantity >= 0);
