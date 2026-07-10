BEGIN;

-- /trade-decisions (date 필터)와 대시보드/의사결정 화면이 매번
-- (created_at AT TIME ZONE 'Asia/Seoul')::date = $1 조건으로 조회하는데,
-- 이 표현식에 대한 인덱스가 없어 Seq Scan(trade_decisions 전체 5만+건)이
-- 발생하고 있었다(EXPLAIN ANALYZE 실측, 2026-07-10). 표현식 인덱스를 추가해
-- 이 조건이 인덱스 스캔을 타도록 한다.
CREATE INDEX IF NOT EXISTS idx_trade_decisions_created_at_kst_date
    ON trading.trade_decisions (((created_at AT TIME ZONE 'Asia/Seoul')::date));

COMMIT;
