-- db/migrations/0023_add_execution_attempts.sql
-- Phase 3: ExecutionAttempt 엔티티 도입 — trade_decision과 실행 흐름 분리
-- 설계 문서: plans/introduce_execution_attempt_entity_to_separate_decision_and_execution_flow_2026-05-23.md

CREATE TABLE trading.execution_attempts (
    execution_attempt_id UUID PRIMARY KEY,
    trade_decision_id UUID NOT NULL REFERENCES trading.trade_decisions(trade_decision_id),
    decision_context_id UUID NOT NULL REFERENCES trading.decision_contexts(decision_context_id),
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    stop_phase VARCHAR(64),
    stop_reason TEXT,
    phase_trace JSONB,
    order_request_id UUID REFERENCES trading.order_requests(order_request_id),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_execution_attempts_trade_decision_id
    ON trading.execution_attempts(trade_decision_id);
CREATE INDEX idx_execution_attempts_decision_context_id
    ON trading.execution_attempts(decision_context_id);
CREATE INDEX idx_execution_attempts_status
    ON trading.execution_attempts(status);

COMMENT ON TABLE trading.execution_attempts IS
    'trading.execution_attempts: 각 trade_decision의 1회 실행 시도를 추적.
     의사결정(trade_decisions)과 실행 흐름(phase progression, order 생성/제출)을
     명시적으로 분리한다. Phase 3 — 도입 설계 문서:
     plans/introduce_execution_attempt_entity_to_separate_decision_and_execution_flow_2026-05-23.md';

COMMENT ON COLUMN trading.execution_attempts.status IS
    'running | stopped | submitted | failed | non_trade | reconcile_required';
COMMENT ON COLUMN trading.execution_attempts.stop_phase IS
    '파이프라인이 중단된 phase 이름 (예: sizing, sell_guard, translation, ...)';
COMMENT ON COLUMN trading.execution_attempts.stop_reason IS
    '중단 사유 (예: sizing_rejected, sell_guard_blocked, decision_hold, ...)';
COMMENT ON COLUMN trading.execution_attempts.phase_trace IS
    'Phase 2 형식과 동일한 JSONB — 각 phase별 elapsed_ms/status 배열';
