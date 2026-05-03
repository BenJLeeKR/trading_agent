-- Migration 0007: Add audit_log_seq to audit_logs for deterministic ordering
--
-- Motivation
-- ----------
-- ``PostgresAuditLogRepository.list_by_correlation_id`` uses
-- ``ORDER BY created_at``.  When multiple rows share the **same**
-- ``created_at`` timestamp (common in batch operations), PostgreSQL
-- returns rows in arbitrary physical storage order, causing
-- non-deterministic test failures.
--
-- Solution
-- --------
-- ``audit_log_seq BIGSERIAL`` provides an auto-incrementing sequence
-- number that guarantees strict insertion order.  The composite sort
-- ``ORDER BY created_at, audit_log_seq`` makes the tie-breaker
-- deterministic.
--
-- Existing data
-- -------------
-- Existing rows are backfilled via ``row_number()`` ordered by
-- ``(created_at NULLS LAST, audit_log_id)`` so that chronological
-- order is preserved deterministically.

BEGIN;

-- 1. Add the sequence column
--    BIGSERIAL auto-creates a sequence named
--    ``trading.audit_logs_audit_log_seq_seq``.
ALTER TABLE trading.audit_logs
    ADD COLUMN audit_log_seq BIGSERIAL;

-- 2. Backfill existing rows with deterministic sequential values
--    Ordered by created_at (NULLs last), then audit_log_id as
--    deterministic tie-breaker for rows with identical timestamps.
UPDATE trading.audit_logs AS t
SET audit_log_seq = s.seq
FROM (
    SELECT
        audit_log_id,
        row_number() OVER (
            ORDER BY created_at NULLS LAST, audit_log_id
        ) AS seq
    FROM trading.audit_logs
) s
WHERE t.audit_log_id = s.audit_log_id;

-- 3. Replace the old single-column index with a composite index
--    that covers both the WHERE filter and the ORDER BY sort,
--    enabling a single index-only scan.
DROP INDEX IF EXISTS trading.idx_audit_logs_correlation_id;

CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation_id_created_seq
    ON trading.audit_logs (correlation_id, created_at DESC, audit_log_seq DESC);

COMMIT;
