-- historical_sell_fee_tax_overlays — 이미 원장에 존재하는 SELL fill_event에
-- 대해 소급 매도 수수료+매도세 추정치를 append-only로 얹는 전용 테이블.
-- 설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
-- snapshot_historical_backfill_design.md §8.15 (`007070` SELL fee/tax
-- historical estimate 파일럿).
--
-- `historical_buy_fee_overlays`(migration 0062)와 같은 원칙 — `fill_events`
-- 원본은 절대 UPDATE하지 않기 위한 별도 사실 저장소다. BUY overlay는
-- `estimated_fee` 한 컬럼만 가지지만(매수에는 세금 개념이 없음), 매도는
-- 매도 수수료(commission)와 매도세(tax)가 별개로 존재하므로 이 테이블은
-- `estimated_fee`/`estimated_tax` 두 컬럼을 함께 가진다 — BUY overlay
-- 테이블을 억지로 재사용하지 않고 별도 테이블로 분리한 이유다.
--
-- `fee_tax_source`는 BUY overlay와 동일하게 `historical_policy_estimate`
-- 하나만 허용한다 — "체결 시각 기준으로는 정책이 없어 assumed_zero였지만,
-- 현재 활성 정책을 소급 추정으로 적용한 값"이라는 인과관계가 BUY/SELL
-- 모두 동일하기 때문에 provenance 값 자체는 재사용하고 새 enum 값을
-- 추가하지 않는다.

CREATE TABLE IF NOT EXISTS trading.historical_sell_fee_tax_overlays (
    overlay_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fill_event_id UUID NOT NULL UNIQUE REFERENCES trading.fill_events (fill_event_id),
    estimated_fee NUMERIC(20, 8) NOT NULL,
    estimated_tax NUMERIC(20, 8) NOT NULL,
    fee_tax_source VARCHAR(32) NOT NULL,
    basis_config_version_id UUID NOT NULL REFERENCES trading.config_versions (config_version_id),
    reason TEXT NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_historical_sell_fee_tax_overlays_estimated_fee CHECK (estimated_fee >= 0),
    CONSTRAINT ck_historical_sell_fee_tax_overlays_estimated_tax CHECK (estimated_tax >= 0),
    CONSTRAINT ck_historical_sell_fee_tax_overlays_fee_tax_source
        CHECK (fee_tax_source = 'historical_policy_estimate'),
    CONSTRAINT ck_historical_sell_fee_tax_overlays_reason_not_blank
        CHECK (btrim(reason) <> '')
);

CREATE INDEX IF NOT EXISTS idx_historical_sell_fee_tax_overlays_fill_event
    ON trading.historical_sell_fee_tax_overlays (fill_event_id);
