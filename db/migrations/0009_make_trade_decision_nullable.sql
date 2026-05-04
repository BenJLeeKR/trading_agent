BEGIN;

-- ============================================================================
-- Migration 0009: Make trade_decisions.decision nullable (Plan 39)
--
-- Problem
-- -------
-- Migration 0001 created ``trade_decisions.decision VARCHAR(32) NOT NULL``
-- with ``CHECK IN ('buy','sell','hold','reduce','exit')``.
--
-- This column is semantically superseded by ``decision_type`` (0004, P0 core
-- field) + ``side`` (0004, P0 core field).  The ``TradeDecisionEntity`` has
-- no ``decision`` field, and ``PostgresTradeDecisionRepository.add()`` does
-- not include ``decision`` in the INSERT.  The ``NOT NULL`` constraint would
-- block any future INSERT through the repository.
--
-- Status: Orphaned legacy column — no code reads or writes it.
--   This migration only relaxes the NOT NULL constraint so the column
--   no longer blocks INSERT.  It is a deprecation candidate for future
--   removal (migration 0010+).
--
-- Fix
-- ---
-- Make ``decision`` nullable so existing INSERT statements (which omit
-- ``decision``) work correctly.  The column remains in the schema for
-- backward compatibility.
-- ============================================================================

ALTER TABLE trading.trade_decisions
    ALTER COLUMN decision DROP NOT NULL;

COMMIT;
