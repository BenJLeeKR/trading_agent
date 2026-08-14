-- fee_tax_source에 historical_policy_estimate 값을 추가한다.
-- 설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
-- snapshot_historical_backfill_design.md §8, 12_realized_pnl_moving_average_
-- ledger.md 13절/14절.
--
-- 이 값은 실시간 계산(calculated_from_policy)과 절대 같은 의미가 아니다 —
-- initial backfill이 명시적 opt-in 옵션으로, 그 체결 당시엔 활성 정책이
-- 없었지만 현재 활성 정책을 소급 추정으로 적용했을 때만 채워진다
-- (historical_fill_backfill.py의 use_historical_policy_estimate_for_buy_fee
-- 옵션 참고).
--
-- forward-safe: 기존 row는 전부 이 새 값과 무관하다(과거 데이터를 이
-- migration이 재작성하지 않는다) — CHECK 제약에 값 하나를 추가하는
-- 것뿐이다.

ALTER TABLE trading.fill_events
    DROP CONSTRAINT ck_fill_events_fee_tax_source;

ALTER TABLE trading.fill_events
    ADD CONSTRAINT ck_fill_events_fee_tax_source
        CHECK (fee_tax_source IS NULL OR fee_tax_source IN (
            'reported',
            'assumed_zero',
            'calculated_from_policy',
            'policy_not_applicable',
            'historical_policy_estimate'
        ));

ALTER TABLE trading.realized_pnl_events
    DROP CONSTRAINT ck_realized_pnl_events_fee_tax_source;

ALTER TABLE trading.realized_pnl_events
    ADD CONSTRAINT ck_realized_pnl_events_fee_tax_source
        CHECK (fee_tax_source IN (
            'reported',
            'assumed_zero',
            'calculated_from_policy',
            'policy_not_applicable',
            'historical_policy_estimate'
        ));
