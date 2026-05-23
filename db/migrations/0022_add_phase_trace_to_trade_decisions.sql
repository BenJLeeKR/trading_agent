-- 0022_add_phase_trace_to_trade_decisions.sql
-- purpose: store phase_trace JSONB on trade_decisions for pipeline observability
ALTER TABLE trading.trade_decisions
    ADD COLUMN phase_trace jsonb;
