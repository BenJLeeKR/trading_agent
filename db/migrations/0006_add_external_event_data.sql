-- Migration 0006: External Event Data Foundation
--
-- This migration adds the external_events table for storing normalised
-- event data from external sources (OpenDART, KRX KIND, news feeds,
-- broker reports, macro calendars, etc.).
--
-- Scope (Milestone 7)
-- -------------------
-- * Schema and storage only — no polling workers or source adapters.
-- * Event classification, source reliability tier, dedup, and freshness
--   budget are enforced at the application layer.
--
-- v1 excluded
-- -----------
-- * Actual OpenDART / KRX KIND API polling.
-- * News feed ingestion.
-- * AI-based event interpretation.

CREATE TABLE IF NOT EXISTS trading.external_events (
    event_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type              TEXT NOT NULL,
    source_name             TEXT NOT NULL,
    source_reliability_tier TEXT NOT NULL DEFAULT 'T3',
    source_event_id         TEXT,
    issuer_code             TEXT,
    symbol                  TEXT,
    market                  TEXT,
    published_at            TIMESTAMPTZ NOT NULL,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_at            TIMESTAMPTZ,
    severity                TEXT NOT NULL DEFAULT 'medium',
    direction               TEXT NOT NULL DEFAULT 'neutral',
    headline                TEXT,
    body_summary            TEXT,
    raw_payload_uri         TEXT,
    dedup_key_hash          TEXT,
    supersedes_event_id     UUID REFERENCES trading.external_events(event_id),
    metadata                JSONB NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_external_events_symbol
    ON trading.external_events (symbol, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_external_events_type
    ON trading.external_events (event_type, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_external_events_dedup
    ON trading.external_events (dedup_key_hash)
    WHERE dedup_key_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_events_source
    ON trading.external_events (source_name, source_event_id)
    WHERE source_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_events_supersedes
    ON trading.external_events (supersedes_event_id)
    WHERE supersedes_event_id IS NOT NULL;
