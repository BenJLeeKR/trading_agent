BEGIN;

-- ============================================================================
-- Migration 0003: Safe Order Path Persistence Tables
--
-- Adds three tables required for the "Safe Order Path" runtime safety layer:
--   1. order_state_events       — append-only audit trail for order transitions
--   2. guardrail_evaluations    — guardrail rule evaluation results
--   3. risk_limit_snapshots     — point-in-time risk limit & exposure snapshots
-- ============================================================================

-- ------------------------------------------------------------------
-- 1. order_state_events
--    Append-only record of every order status transition.
--    This is a SUPPLEMENTARY audit trail, NOT a replacement for the
--    current-state stored in order_requests.status.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.order_state_events (
    order_state_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_request_id     UUID NOT NULL REFERENCES trading.order_requests (order_request_id),
    previous_status     VARCHAR(32),
    new_status          VARCHAR(32) NOT NULL,
    event_source        VARCHAR(32) NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason_code         VARCHAR(128),
    raw_event_uri       TEXT,
    correlation_id      VARCHAR(128),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_state_events_order_request_id
    ON trading.order_state_events (order_request_id);
CREATE INDEX IF NOT EXISTS idx_order_state_events_ingested_at
    ON trading.order_state_events (ingested_at);

COMMENT ON TABLE trading.order_state_events IS
    'Append-only audit trail for order status transitions. '
    'Do NOT UPDATE or DELETE rows in this table.';
COMMENT ON COLUMN trading.order_state_events.event_source IS
    'Origin of the event: internal, broker_rest, broker_ws, reconciliation, operator';
COMMENT ON COLUMN trading.order_state_events.previous_status IS
    'NULL for the very first event (DRAFT has no previous status).';

-- ------------------------------------------------------------------
-- 2. guardrail_evaluations
--    Stores the result of every guardrail rule evaluation.
--    Linked to a decision context, trade decision, or order request.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.guardrail_evaluations (
    guardrail_evaluation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_context_id     UUID REFERENCES trading.decision_contexts (decision_context_id),
    trade_decision_id       UUID REFERENCES trading.trade_decisions (trade_decision_id),
    order_request_id        UUID REFERENCES trading.order_requests (order_request_id),
    rule_set_version        VARCHAR(64) NOT NULL,
    overall_passed          BOOLEAN NOT NULL,
    evaluated_at            TIMESTAMPTZ NOT NULL,
    rule_results            JSONB NOT NULL DEFAULT '{}'::jsonb,
    blocking_rule_codes     TEXT[],
    warning_rule_codes      TEXT[],
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guardrail_evaluations_decision_context
    ON trading.guardrail_evaluations (decision_context_id);
CREATE INDEX IF NOT EXISTS idx_guardrail_evaluations_order_request
    ON trading.guardrail_evaluations (order_request_id);

COMMENT ON TABLE trading.guardrail_evaluations IS
    'Guardrail rule evaluation results. All 3 FKs are nullable because '
    'guardrails may be evaluated at decision time, order time, or both.';
COMMENT ON COLUMN trading.guardrail_evaluations.rule_results IS
    'JSONB map of rule_code -> evaluation_detail for extensibility.';

-- ------------------------------------------------------------------
-- 3. risk_limit_snapshots
--    Point-in-time snapshot of risk limits and exposure for an account.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.risk_limit_snapshots (
    risk_limit_snapshot_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID NOT NULL REFERENCES trading.accounts (account_id),
    snapshot_at             TIMESTAMPTZ NOT NULL,
    nav                     NUMERIC(24, 8),
    cash_available          NUMERIC(24, 8),
    gross_exposure_pct      NUMERIC(10, 4),
    net_exposure_pct        NUMERIC(10, 4),
    daily_realized_pnl      NUMERIC(20, 8),
    daily_unrealized_pnl    NUMERIC(20, 8),
    daily_loss_used_pct     NUMERIC(10, 4),
    max_daily_loss_limit_pct NUMERIC(10, 4),
    symbol_exposure_json    JSONB DEFAULT '{}'::jsonb,
    sector_exposure_json    JSONB DEFAULT '{}'::jsonb,
    open_order_exposure_json JSONB DEFAULT '{}'::jsonb,
    drawdown_state          VARCHAR(32),
    kill_switch_active      BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason_codes    TEXT[],
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_limit_snapshots_account
    ON trading.risk_limit_snapshots (account_id, snapshot_at DESC);

COMMENT ON TABLE trading.risk_limit_snapshots IS
    'Point-in-time risk limit and exposure snapshot per account.';
COMMENT ON COLUMN trading.risk_limit_snapshots.kill_switch_active IS
    'Hard guardrail kill-switch state at snapshot time.';
COMMENT ON COLUMN trading.risk_limit_snapshots.symbol_exposure_json IS
    'JSONB map of symbol -> exposure_pct for extensibility.';
COMMENT ON COLUMN trading.risk_limit_snapshots.sector_exposure_json IS
    'JSONB map of sector -> exposure_pct for extensibility.';
COMMENT ON COLUMN trading.risk_limit_snapshots.open_order_exposure_json IS
    'JSONB map of order_request_id -> exposure_pct for extensibility.';

COMMIT;
