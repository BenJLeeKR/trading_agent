-- KIS 누적 체결량 관측 상태(kis_fill_cumulative_state) 신규 테이블.
-- 설계 근거: docs/00_foundational_design/detailed_design/14_kis_fill_
-- normalization_and_incremental_interpretation_design.md 3.2절(안 C).
-- 실행 계획: docs/40_action_plans/kis_fill_normalization_action_plan.md
--
-- 이 테이블은 fill_events(진실의 원천, 증분만 append)의 대체가 아니다 —
-- order_sync_service._sync_fills()가 KIS TOT_CCLD_QTY(누적값)를 증분
-- fill로 안전하게 변환하기 위한 계좌×브로커주문번호 단위 보조 관측
-- 상태(cache)다. 이 상태가 손상/재구축되어도 이미 append된 fill_events는
-- 바뀌지 않는다.

CREATE TABLE IF NOT EXISTS trading.kis_fill_cumulative_state (
    kis_fill_cumulative_state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    broker_name VARCHAR(64) NOT NULL,
    broker_native_order_id VARCHAR(128) NOT NULL,
    last_cumulative_filled_quantity NUMERIC(24, 8) NOT NULL DEFAULT 0,
    last_average_fill_price NUMERIC(20, 8),
    last_observed_at TIMESTAMPTZ NOT NULL,
    last_raw_field_fingerprint VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_kis_fill_cumulative_state_account_broker_order
        UNIQUE (account_id, broker_name, broker_native_order_id),
    CONSTRAINT ck_kis_fill_cumulative_state_qty_non_negative
        CHECK (last_cumulative_filled_quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_kis_fill_cumulative_state_account
    ON trading.kis_fill_cumulative_state (account_id, updated_at DESC);
