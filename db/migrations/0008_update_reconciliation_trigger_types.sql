-- Migration 0008: Align schema constraints with production code values
--
-- Fixes 3 schema/code mismatches discovered during Plan 38 Postgres
-- E2E test activation:
--
-- 1. ``reconciliation_runs.trigger_type`` CHECK (0001) — missing
--    ``'uncertain_result'`` and ``'requires_reconciliation'`` values
--    used by ``OrderManager.submit_order_to_broker``.
--
-- 2. ``reconciliation_runs.status`` CHECK (0001) — missing
--    ``'resolved'`` and ``'reflection_failed'`` values used by
--    ``ReconciliationService.mark_resolved`` and
--    ``transition_to_authoritative``.
--
-- 3. ``order_blocking_locks.strategy_id`` (0005) — declared ``NOT NULL``
--    but ``ReconciliationService.acquire_blocking_lock`` accepts
--    ``strategy_id=None``, and the call site in ``OrderManager`` does
--    not pass a strategy_id.

BEGIN;

-- === Fix 1: Update reconciliation_runs trigger_type CHECK ===

ALTER TABLE trading.reconciliation_runs
    DROP CONSTRAINT IF EXISTS ck_reconciliation_runs_trigger;

ALTER TABLE trading.reconciliation_runs
    ADD CONSTRAINT ck_reconciliation_runs_trigger
        CHECK (trigger_type IN (
            'schedule', 'submit_timeout', 'ws_disconnect', 'manual', 'eod',
            'uncertain_result', 'requires_reconciliation'
        ));

-- === Fix 2: Update reconciliation_runs status CHECK ===
--
-- Production code uses 'resolved' (mark_resolved) and 'reflection_failed'
-- (transition_to_authoritative failure path).

ALTER TABLE trading.reconciliation_runs
    DROP CONSTRAINT IF EXISTS ck_reconciliation_runs_status;

ALTER TABLE trading.reconciliation_runs
    ADD CONSTRAINT ck_reconciliation_runs_status
        CHECK (status IN (
            'started', 'completed', 'failed', 'halted',
            'resolved', 'reflection_failed'
        ));

-- === Fix 3: Make order_blocking_locks.strategy_id nullable ===
--
-- Production code passes ``strategy_id=None`` when the lock scope
-- does not require a specific strategy (blanket lock for the entire
-- account).

ALTER TABLE trading.order_blocking_locks
    ALTER COLUMN strategy_id DROP NOT NULL;

-- Drop and recreate the UNIQUE constraint to allow NULL strategy_id.
-- PostgreSQL's UNIQUE constraint treats NULLs as distinct, so
-- (account_id, NULL, symbol, side) is unique per account.

ALTER TABLE trading.order_blocking_locks
    DROP CONSTRAINT IF EXISTS uq_order_blocking_locks_key;

ALTER TABLE trading.order_blocking_locks
    ADD CONSTRAINT uq_order_blocking_locks_key
        UNIQUE (account_id, strategy_id, symbol, side);

COMMIT;
