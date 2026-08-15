-- historical_buy_fee_overlays — 이미 원장에 존재하는 BUY fill_event에
-- 대해 소급 fee 추정치를 append-only로 얹는 전용 테이블.
-- 설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
-- snapshot_historical_backfill_design.md §8.13 (`007070` overlay+recompute
-- 파일럿).
--
-- 이 테이블은 `fill_events`를 절대 UPDATE하지 않기 위한 별도 사실
-- 저장소다 — "이 fill에 대해 이런 historical fee 추정치가 있다"는
-- 새로운 사실만 append하고, recompute 경로만 이 값을 읽어 병합한다.
-- 실시간 경로(order_sync_service)는 이 테이블을 전혀 참조하지 않는다.

CREATE TABLE IF NOT EXISTS trading.historical_buy_fee_overlays (
    overlay_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fill_event_id UUID NOT NULL UNIQUE REFERENCES trading.fill_events (fill_event_id),
    estimated_fee NUMERIC(20, 8) NOT NULL,
    fee_tax_source VARCHAR(32) NOT NULL,
    basis_config_version_id UUID NOT NULL REFERENCES trading.config_versions (config_version_id),
    reason TEXT NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_historical_buy_fee_overlays_estimated_fee CHECK (estimated_fee >= 0),
    CONSTRAINT ck_historical_buy_fee_overlays_fee_tax_source
        CHECK (fee_tax_source = 'historical_policy_estimate'),
    CONSTRAINT ck_historical_buy_fee_overlays_reason_not_blank
        CHECK (btrim(reason) <> '')
);

CREATE INDEX IF NOT EXISTS idx_historical_buy_fee_overlays_fill_event
    ON trading.historical_buy_fee_overlays (fill_event_id);
