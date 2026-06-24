CREATE TABLE IF NOT EXISTS trading.symbol_trade_states (
    symbol_trade_state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id) ON DELETE CASCADE,
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    state TEXT NOT NULL,
    holding_profile TEXT NULL,
    position_quantity NUMERIC(24, 8) NOT NULL DEFAULT 0,
    last_entry_order_request_id UUID NULL
        REFERENCES trading.order_requests (order_request_id) ON DELETE SET NULL,
    last_exit_order_request_id UUID NULL
        REFERENCES trading.order_requests (order_request_id) ON DELETE SET NULL,
    last_entry_source_type TEXT NULL,
    last_entry_at TIMESTAMPTZ NULL,
    last_reduce_at TIMESTAMPTZ NULL,
    last_exit_at TIMESTAMPTZ NULL,
    minimum_hold_until TIMESTAMPTZ NULL,
    reentry_cooldown_until TIMESTAMPTZ NULL,
    sell_cooldown_until TIMESTAMPTZ NULL,
    last_signal_feature_snapshot_id UUID NULL
        REFERENCES trading.signal_feature_snapshots (signal_feature_snapshot_id) ON DELETE SET NULL,
    last_decision_context_id UUID NULL
        REFERENCES trading.decision_contexts (decision_context_id) ON DELETE SET NULL,
    last_reason_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    thesis_state_hash TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_symbol_trade_states_account_instrument UNIQUE (account_id, instrument_id),
    CONSTRAINT ck_symbol_trade_states_state
        CHECK (state IN (
            'flat',
            'entry_pending',
            'held_active',
            'reduce_pending',
            'exit_pending',
            'flat_cooldown'
        ))
);

CREATE INDEX IF NOT EXISTS idx_symbol_trade_states_account_state
    ON trading.symbol_trade_states (account_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_symbol_trade_states_account_symbol
    ON trading.symbol_trade_states (account_id, symbol, market);

CREATE INDEX IF NOT EXISTS idx_symbol_trade_states_reentry_cooldown
    ON trading.symbol_trade_states (reentry_cooldown_until)
    WHERE reentry_cooldown_until IS NOT NULL;

COMMENT ON TABLE trading.symbol_trade_states IS
    '심볼 단위 진입/보유/축소 상태와 cooldown을 저장하는 authoritative 상태 캐시.';

COMMENT ON COLUMN trading.symbol_trade_states.state IS
    'flat, entry_pending, held_active, reduce_pending, exit_pending, flat_cooldown';

COMMENT ON COLUMN trading.symbol_trade_states.holding_profile IS
    'event_probe, event_swing, core_swing 등 기대 보유기간/행동 profile.';
