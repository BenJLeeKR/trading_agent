BEGIN;

-- ============================================================================
-- Migration 0013: Add source_type column to trade_decisions table
--
-- Adds a VARCHAR(32) column to track the origin of each trade decision:
--   "core", "held_position", "event_overlay", "market_overlay", "manual"
--
-- The column is nullable so existing rows are not affected.
-- No backfill is required.
-- ============================================================================

ALTER TABLE trading.trade_decisions
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(32) NULL;

COMMIT;
