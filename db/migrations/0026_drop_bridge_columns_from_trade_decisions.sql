-- 0026: Phase 7.1 — Remove execution bridge columns from trade_decisions
-- Bridge period 종료: execution read/write는 ExecutionAttempt가 단일 truth
-- trade_decisions는 decision truth만 담당

ALTER TABLE trading.trade_decisions
    DROP COLUMN IF EXISTS pipeline_stop_phase,
    DROP COLUMN IF EXISTS pipeline_stop_reason,
    DROP COLUMN IF EXISTS pipeline_stopped_at,
    DROP COLUMN IF EXISTS phase_trace;
