BEGIN;

-- ============================================================================
-- Migration 0005: Order Tracing Fields + Order Blocking Locks
--
-- 1. order_requests — add decision_context_id (P0) and order_intent_id (P1)
-- 2. order_blocking_locks — new table for unknown-state blocking locks
--
-- Both changes are backward-compatible: ADD COLUMN IF NOT EXISTS.
-- ============================================================================

-- ------------------------------------------------------------------
-- 1. order_requests tracing fields
-- ------------------------------------------------------------------
ALTER TABLE trading.order_requests
    ADD COLUMN IF NOT EXISTS decision_context_id UUID
        REFERENCES trading.decision_contexts (decision_context_id);

ALTER TABLE trading.order_requests
    ADD COLUMN IF NOT EXISTS order_intent_id UUID;

COMMENT ON COLUMN trading.order_requests.decision_context_id IS
    'P0: References the DecisionContext that produced this order.';
COMMENT ON COLUMN trading.order_requests.order_intent_id IS
    'P1 optional: References an order_intent entity if implemented.';

CREATE INDEX IF NOT EXISTS idx_order_requests_decision_context
    ON trading.order_requests (decision_context_id)
    WHERE decision_context_id IS NOT NULL;

-- ------------------------------------------------------------------
-- 2. order_blocking_locks
--    Blocks new orders for a specific (account, strategy, symbol, side)
--    when an order is in an unknown/reconcile-required state.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.order_blocking_locks (
    lock_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          UUID NOT NULL REFERENCES trading.accounts (account_id),
    strategy_id         UUID NOT NULL REFERENCES trading.strategies (strategy_id),
    symbol              VARCHAR(20) NOT NULL,
    side                VARCHAR(8) NOT NULL,
    reason              VARCHAR(255) NOT NULL,
    locked_by_run_id    UUID NOT NULL REFERENCES trading.reconciliation_runs (reconciliation_run_id),
    locked_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 minutes',

    CONSTRAINT uq_order_blocking_locks_key
        UNIQUE (account_id, strategy_id, symbol, side),

    CONSTRAINT ck_order_blocking_locks_side
        CHECK (side IN ('buy', 'sell'))
);

CREATE INDEX IF NOT EXISTS idx_order_blocking_locks_expires
    ON trading.order_blocking_locks (expires_at);

COMMENT ON TABLE trading.order_blocking_locks IS
    'Blocks new orders for (account, strategy, symbol, side) when an order '
    'is in an unknown/reconcile-required state. Locks auto-expire after 30 minutes.';
COMMENT ON COLUMN trading.order_blocking_locks.locked_by_run_id IS
    'FK to the reconciliation run that created this lock.';

COMMIT;
