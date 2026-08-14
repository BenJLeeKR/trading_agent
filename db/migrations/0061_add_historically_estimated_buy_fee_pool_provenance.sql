-- buy_fee_pool_provenance / buy_fee_allocation_source에 historically_estimated
-- 값을 추가한다.
-- 설계 근거: docs/00_foundational_design/detailed_design/
-- 12_realized_pnl_moving_average_ledger.md 14절, docs/00_foundational_design/
-- detailed_design/16_broker_fill_snapshot_historical_backfill_design.md §8.9/§8.10.
--
-- 배경: historical_policy_estimate(fill_events.fee_tax_source, migration 0060)로
-- 계산된 BUY fee는 remaining_buy_fee_pool에 금액은 정확히 반영되지만,
-- 기존 3값 체계(fully_calculated/fully_assumed_zero/partially_assumed_zero)
-- 로는 calculated_from_policy와 구분 없이 fully_assumed_zero로 오분류됐다
-- (calculated-ish 집합에 historical_policy_estimate가 빠져 있었음).
-- historical_policy_estimate(소급 추정)와 calculated_from_policy(그 시점
-- 실제 활성 정책)는 인과관계가 달라 같은 provenance로 섞으면 안 되므로,
-- 별도 값을 추가해 pool 요약 레벨에서도 분리 보존한다.
--
-- forward-safe: 기존 row(fully_calculated/fully_assumed_zero/
-- partially_assumed_zero만 존재)는 이 migration으로 재작성되지 않는다 —
-- CHECK 제약에 값 하나를 추가하는 것뿐이다. 이미 잘못 분류된
-- 001450/004370의 fully_assumed_zero row는 이 migration이 아니라 별도
-- recompute로 바로잡는다(fill_events 원본은 이미 정확하므로 UPDATE 불필요).

ALTER TABLE trading.position_cost_basis_state
    DROP CONSTRAINT ck_position_cost_basis_state_buy_fee_pool_provenance;

ALTER TABLE trading.position_cost_basis_state
    ADD CONSTRAINT ck_position_cost_basis_state_buy_fee_pool_provenance
        CHECK (buy_fee_pool_provenance IN (
            'fully_calculated',
            'fully_assumed_zero',
            'partially_assumed_zero',
            'historically_estimated'
        ));

ALTER TABLE trading.realized_pnl_events
    DROP CONSTRAINT ck_realized_pnl_events_buy_fee_allocation_source;

ALTER TABLE trading.realized_pnl_events
    ADD CONSTRAINT ck_realized_pnl_events_buy_fee_allocation_source
        CHECK (buy_fee_allocation_source IN (
            'fully_calculated',
            'fully_assumed_zero',
            'partially_assumed_zero',
            'historically_estimated'
        ));
