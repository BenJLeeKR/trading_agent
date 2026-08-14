-- realized_pnl_events.fee_tax_source provenance 4값 확장.
-- 설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md 13절
--
-- 기존 2값('reported', 'assumed_zero')에 'calculated_from_policy',
-- 'policy_not_applicable' 2개를 추가한다. 두 신규 값(22자/21자)이 기존
-- VARCHAR(16)을 초과하므로, CHECK 제약 교체 전에 컬럼 폭부터 넓혀야 한다.
--
-- 순서: CHECK 제거 -> 컬럼 타입 확장(VARCHAR(16) -> VARCHAR(32)) -> 새 CHECK 재추가.
-- 폭을 넓히는 변경이라 기존 값('reported'/'assumed_zero')은 그대로 유지된다
-- (데이터 변환/손실 없음).
--
-- rollback 주의: 이 저장소의 기존 migration들은 down-migration 스크립트를
-- 두지 않는 관례다(0001~0056 전체 확인, rollback SQL 없음). 이 migration도
-- 그 관례를 따라 별도 rollback 파일을 두지 않는다. 다만 이 컬럼을 다시
-- VARCHAR(16)으로 되돌리려는 시도가 있다면, 'calculated_from_policy' 또는
-- 'policy_not_applicable' 값이 이미 저장된 행이 있는지 반드시 먼저 확인해야
-- 한다 - 폭을 좁히는 변경은 그 값들을 담지 못해 실패하거나 데이터를 자른다.

ALTER TABLE trading.realized_pnl_events
    DROP CONSTRAINT ck_realized_pnl_events_fee_tax_source;

ALTER TABLE trading.realized_pnl_events
    ALTER COLUMN fee_tax_source TYPE VARCHAR(32);

ALTER TABLE trading.realized_pnl_events
    ADD CONSTRAINT ck_realized_pnl_events_fee_tax_source
        CHECK (fee_tax_source IN (
            'reported',
            'assumed_zero',
            'calculated_from_policy',
            'policy_not_applicable'
        ));
