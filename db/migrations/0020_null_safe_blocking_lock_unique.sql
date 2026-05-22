-- Migration 0020: NULL-safe unique index for order_blocking_locks
--
-- Problem
-- -------
-- PostgreSQL's UNIQUE constraint treats NULLs as distinct, so
-- ``(account_id, NULL, symbol, side)`` rows are **not** considered
-- conflicting.  This means ``ON CONFLICT DO NOTHING`` / ``DO UPDATE``
-- never fires when ``strategy_id IS NULL``, allowing multiple locks
-- for the same (account_id, symbol, side) to coexist silently.
--
-- This was the root cause of the 10:17 KST held_position sell blocking
-- issue (2026-05-22): each BUDGET_EXHAUSTED → trigger() call created
-- a new reconciliation run, and each run's ``acquire_blocking_lock()``
-- inserted a new lock row instead of updating the existing one.
-- Consequently, ``release_blocking_lock(locked_by_run_id=...)`` only
-- matched the first lock's owner, leaving subsequent locks in place.
--
-- Fix
-- ---
-- Replace the UNIQUE constraint with a ``COALESCE``-based expression
-- index.  ``COALESCE(strategy_id, '00000000-...'::uuid)`` maps NULL
-- to a sentinel UUID so that all rows with ``strategy_id IS NULL``
-- are treated as equal by the uniqueness check.
--
-- The ``ON CONFLICT`` clause in ``acquire_blocking_lock()`` has been
-- updated to match this expression index.
--
-- See Also
-- --------
-- ``src/agent_trading/services/reconciliation_service.py`` —
-- ``acquire_blocking_lock()`` now uses:
--
-- .. code-block:: sql
--
--    ON CONFLICT (account_id,
--                 COALESCE(strategy_id, '00000000-0000-0000-0000-000000000000'::uuid),
--                 symbol, side)
--    DO UPDATE SET ...
--        WHERE trading.order_blocking_locks.expires_at < NOW()

BEGIN;

-- ── Step 1: Drop the old UNIQUE constraint ──────────────────────────
-- The constraint was created in migration 0008 with name
-- ``uq_order_blocking_locks_key``.
ALTER TABLE trading.order_blocking_locks
    DROP CONSTRAINT IF EXISTS uq_order_blocking_locks_key;

-- ── Step 2: Create a NULL-safe expression index ─────────────────────
-- ``COALESCE(strategy_id, sentinel_uuid)`` ensures that NULLs are
-- treated as equal for uniqueness purposes.
--
-- The sentinel UUID ``00000000-0000-0000-0000-000000000000`` is chosen
-- because it is unlikely to collide with any real ``strategy_id`` value.
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_blocking_locks_key
    ON trading.order_blocking_locks (
        account_id,
        COALESCE(strategy_id, '00000000-0000-0000-0000-000000000000'::uuid),
        symbol,
        side
    );

-- ── Step 3: Clean up any duplicate locks that may have accumulated ──
-- Due to the NULL-distinct bug, multiple locks may exist for the same
-- (account_id, NULL, symbol, side).  Keep only the **most recently
-- created** lock for each unique scope, and delete the rest.
--
-- This is a one-time cleanup for production data.
WITH duplicates AS (
    SELECT lock_id,
           account_id,
           strategy_id,
           symbol,
           side,
           locked_at,
           ROW_NUMBER() OVER (
               PARTITION BY account_id,
                            COALESCE(strategy_id, '00000000-0000-0000-0000-000000000000'::uuid),
                            symbol,
                            side
               ORDER BY locked_at DESC
           ) AS rn
    FROM trading.order_blocking_locks
)
DELETE FROM trading.order_blocking_locks
WHERE lock_id IN (
    SELECT lock_id FROM duplicates WHERE rn > 1
);

COMMIT;
