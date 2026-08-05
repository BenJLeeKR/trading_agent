-- realized_pnl_daily_aggregates에 매수금액/매도금액/비용 일자 합계 컬럼을
-- 추가한다. Admin UI 실현손익 화면 설계서(design/realized_pnl_screen_spec.md)
-- 기준으로, 종목 "전체" 조회(화면 기본 상태)가 매번 realized_pnl_events
-- 전량을 페이지네이션으로 훑어야 하는 문제를 없애기 위한 선행 백엔드 작업이다.
--
-- 이 컬럼들은 새로운 손익 계산식이 아니다 — 이미 realized_pnl_events에
-- 저장된 필드로부터 파생되는 "UI용 일자 합계 캐시"다(상세 설계 문서
-- 4.3절과 동일한 성격: realized_pnl_events에서 언제든 재생성 가능).
--
--   buy_amount_sum  = Σ(sell_quantity × avg_cost_basis_before)  (그 매도분의 원가 총액)
--   sell_amount_sum = Σ(sell_quantity × sell_price)
--   fee_tax_sum     = Σ(fee + tax)
--
-- NOT NULL + DEFAULT 0으로 추가한다(PostgreSQL 11+ 에서 상수 DEFAULT를 둔
-- 컬럼 추가는 테이블 재작성 없는 메타데이터 전용 변경이라 비파괴적이다).
-- 기존에 이미 쌓인 행은 이 migration만으로는 값이 0으로 남는다 — 실제
-- 매수금액/매도금액/비용을 채우려면 해당 계좌×종목에 대해
-- RealizedPnlRecomputeService.recompute_account_instrument()를 통한
-- 재계산(절대값 재구성)이 필요하다. 신규 fill은 실시간 반영 경로
-- (RealizedPnlLedgerService._update_daily_aggregate)가 곧바로 채운다.

ALTER TABLE trading.realized_pnl_daily_aggregates
    ADD COLUMN IF NOT EXISTS buy_amount_sum NUMERIC(20, 8) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sell_amount_sum NUMERIC(20, 8) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS fee_tax_sum NUMERIC(20, 8) NOT NULL DEFAULT 0;
