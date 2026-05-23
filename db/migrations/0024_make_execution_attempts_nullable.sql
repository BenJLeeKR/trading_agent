-- db/migrations/0024_make_execution_attempts_nullable.sql
-- Phase 4: ExecutionAttempt를 write-path 중심으로 승격 + Pipeline 분리 1차
-- 설계 문서: plans/promote_execution_attempt_as_primary_execution_truth_and_begin_pipeline_split_2026-05-23.md
--
-- ExecutionAttempt가 primary truth가 되면서, ExecutionAttempt가 먼저 생성되고
-- 이후에 TradeDecision이 생성되는 순서가 가능해짐. 따라서 trade_decision_id와
-- decision_context_id가 NOT NULL일 필요가 없어짐.

ALTER TABLE trading.execution_attempts
    ALTER COLUMN trade_decision_id DROP NOT NULL;

ALTER TABLE trading.execution_attempts
    ALTER COLUMN decision_context_id DROP NOT NULL;

COMMENT ON COLUMN trading.execution_attempts.trade_decision_id IS
    '연결된 TradeDecision (nullable). ExecutionAttempt가 primary truth일 경우,
     trade_decision이 생성되기 전에 execution_attempt가 먼저 생성될 수 있음.';
COMMENT ON COLUMN trading.execution_attempts.decision_context_id IS
    '연결된 DecisionContext (nullable). 위와 동일한 이유로 nullable 허용.';
