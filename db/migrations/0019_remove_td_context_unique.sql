-- Migration: trade_decisions.decision_context_id UNIQUE 제약 제거
-- 목적: 동일 decision_context에 대해 여러 TD row 허용 (INSERT-only 정책)

BEGIN;

ALTER TABLE trading.trade_decisions
    DROP CONSTRAINT IF EXISTS trade_decisions_decision_context_id_key;

CREATE INDEX IF NOT EXISTS idx_trade_decisions_context_created
    ON trading.trade_decisions (decision_context_id, created_at DESC, trade_decision_id DESC);

COMMIT;

-- ROLLBACK:
-- BEGIN;
-- DROP INDEX IF EXISTS idx_trade_decisions_context_created;
-- ALTER TABLE trading.trade_decisions
--     ADD CONSTRAINT trade_decisions_decision_context_id_key UNIQUE (decision_context_id);
-- -- 참고: Rollback 시 duplicate row가 있으면 UNIQUE 재추가 실패 가능
-- COMMIT;
