BEGIN;

-- /trade-decisions는 필터(decision_context_id 등) 없이도 항상
-- ORDER BY created_at DESC, trade_decision_id DESC LIMIT ... OFFSET ...로
-- 페이지네이션한다. created_at 단독/복합 인덱스가 없어(기존
-- idx_trade_decisions_context_created는 decision_context_id가 선두 컬럼이라
-- 이 쿼리엔 못 쓰임) 매 요청마다 5만+건 전체를 디스크 기반 외부 정렬
-- (Sort Method: external merge)하고 있었다(EXPLAIN ANALYZE 실측, 2026-07-10).
CREATE INDEX IF NOT EXISTS idx_trade_decisions_created_at_desc
    ON trading.trade_decisions (created_at DESC, trade_decision_id DESC);

COMMIT;
