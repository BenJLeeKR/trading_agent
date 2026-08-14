-- fill_events.fee_tax_source 추가 — 정책 기반 fee/tax 계산의 provenance를
-- realized_pnl_ledger_service까지 그대로 전달하기 위한 컬럼.
-- 설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md 13절
--
-- realized_pnl_events.fee_tax_source(0057 migration)는 이미 4값을 지원하지만,
-- 그 값은 fill_events.fill_fee/fill_tax가 NULL인지 아닌지만 보고
-- realized_pnl_ledger_service._normalize_fee_tax()가 사후에 추론했다 —
-- 그 추론 규칙은 reported/assumed_zero 2값만 구분할 수 있고,
-- calculated_from_policy/policy_not_applicable을 만들 방법이 없었다.
--
-- 이 컬럼은 nullable이다 — 기존 writer(브로커 응답 관측)는 이 컬럼을
-- 채우지 않아도 되고, 그 경우 realized_pnl_ledger_service는 기존
-- None 기반 추론 규칙으로 계속 동작한다(하위 호환).

ALTER TABLE trading.fill_events
    ADD COLUMN fee_tax_source VARCHAR(32);

ALTER TABLE trading.fill_events
    ADD CONSTRAINT ck_fill_events_fee_tax_source
        CHECK (fee_tax_source IS NULL OR fee_tax_source IN (
            'reported',
            'assumed_zero',
            'calculated_from_policy',
            'policy_not_applicable'
        ));
