-- agent_runs.started_at 단독 인덱스.
-- GET /agent-runs (list_all, ORDER BY started_at DESC LIMIT 100)가
-- decision_context_id 필터 없이 started_at만으로 정렬/제한하는데,
-- 기존 idx_agent_runs_decision_context(decision_context_id, started_at DESC)는
-- 선두 컬럼이 decision_context_id라 이 조회에 쓰이지 않아 매번
-- agent_runs 전체(약 20만 행, 계속 증가)를 Parallel Seq Scan한다.
-- 실측(EXPLAIN ANALYZE, 197k행 기준): Execution Time 61.86ms,
-- Buffers: shared hit=5316 read=22831 — OperationsAlertsView 로딩 지연의
-- 구성 요소 중 하나로 확인됨.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at
    ON trading.agent_runs (started_at DESC);
COMMIT;
