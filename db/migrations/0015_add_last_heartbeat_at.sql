BEGIN;

-- ============================================================================
-- Migration 0015: Add last_heartbeat_at column to market_sessions
--
-- Adds the `last_heartbeat_at` column used by the ops-scheduler heartbeat
-- task and Docker healthcheck.  The heartbeat task updates this column every
-- 10 seconds; the healthcheck reads it to determine container freshness.
--
-- Depends on: 0014_add_market_session_tables.sql
-- ============================================================================

ALTER TABLE trading.market_sessions
ADD COLUMN last_heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN trading.market_sessions.last_heartbeat_at
    IS '스케줄러 heartbeat 마지막 갱신 시각 — 10초 간격, healthcheck에서 사용';

COMMIT;
