-- average_cost는 건드리지 않고, 매수(BUY) 수수료를 별도 pool로 누적했다가
-- 매도(SELL) 시점에 보유수량 대비 매도수량 비율로 realized_pnl_net에
-- 배분(allocate)하기 위한 컬럼 추가 — C안 확장형.
-- 설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md 14절
--
-- position_cost_basis_state.remaining_buy_fee_pool:
--   현재 보유 수량에 대응하는, 아직 SELL에 배분되지 않은 누적 매수 수수료.
--   불변식: quantity = 0이면 이 값도 반드시 0이다(전량 청산 시 전액 배분).
-- position_cost_basis_state.buy_fee_pool_provenance:
--   위 pool을 구성하는 BUY들의 fee_tax_source 요약(개별 BUY lot 추적이
--   아니라 "지금 쌓인 pool 전체가 어떤 신뢰도인가"만 요약한다 — 이동평균
--   모델은 애초에 BUY를 lot으로 구분하지 않기 때문).
--
-- realized_pnl_events.allocated_buy_fee:
--   이번 SELL에 배분된 매수 수수료 몫. 기존 fee(이번 SELL 자체의 매도
--   수수료)와는 감사 목적상 절대 합쳐 넣지 않고 분리 보존한다.
-- realized_pnl_events.buy_fee_allocation_source:
--   배분 시점 remaining_buy_fee_pool의 provenance 요약 스냅샷.
--
-- 기본값 전략(forward-only 안전성):
--   기존 row는 전부 매수 수수료가 0/NULL이었던 시절 데이터이므로(정책이
--   이번에 막 등록됐다 — docs 12번 13절), remaining_buy_fee_pool=0,
--   buy_fee_pool_provenance='fully_assumed_zero' 기본값이 실제 사실과
--   정확히 일치한다. 과거 row에 대한 소급 재계산/대량 backfill은
--   필요하지 않다 — 새 컬럼에 기본값만 채우면 그대로 진실이다.

ALTER TABLE trading.position_cost_basis_state
    ADD COLUMN remaining_buy_fee_pool NUMERIC(20,8) NOT NULL DEFAULT 0,
    ADD COLUMN buy_fee_pool_provenance VARCHAR(32) NOT NULL DEFAULT 'fully_assumed_zero';

ALTER TABLE trading.position_cost_basis_state
    ADD CONSTRAINT ck_position_cost_basis_state_remaining_buy_fee_pool
        CHECK (remaining_buy_fee_pool >= 0);

ALTER TABLE trading.position_cost_basis_state
    ADD CONSTRAINT ck_position_cost_basis_state_buy_fee_pool_provenance
        CHECK (buy_fee_pool_provenance IN (
            'fully_calculated',
            'fully_assumed_zero',
            'partially_assumed_zero'
        ));

ALTER TABLE trading.realized_pnl_events
    ADD COLUMN allocated_buy_fee NUMERIC(20,8) NOT NULL DEFAULT 0,
    ADD COLUMN buy_fee_allocation_source VARCHAR(32) NOT NULL DEFAULT 'fully_assumed_zero';

ALTER TABLE trading.realized_pnl_events
    ADD CONSTRAINT ck_realized_pnl_events_allocated_buy_fee
        CHECK (allocated_buy_fee >= 0);

ALTER TABLE trading.realized_pnl_events
    ADD CONSTRAINT ck_realized_pnl_events_buy_fee_allocation_source
        CHECK (buy_fee_allocation_source IN (
            'fully_calculated',
            'fully_assumed_zero',
            'partially_assumed_zero'
        ));
