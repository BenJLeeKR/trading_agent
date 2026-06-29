CREATE TABLE IF NOT EXISTS trading.instrument_status_snapshots (
    instrument_status_snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id) ON DELETE CASCADE,
    snapshot_at TIMESTAMPTZ NOT NULL,
    source_type TEXT NOT NULL,
    status_scope TEXT NOT NULL,
    tr_stop_yn TEXT NULL,
    admn_item_yn TEXT NULL,
    nxt_tr_stop_yn TEXT NULL,
    temp_stop_yn TEXT NULL,
    iscd_stat_cls_code TEXT NULL,
    mket_id_cd TEXT NULL,
    scty_grp_id_cd TEXT NULL,
    excg_dvsn_cd TEXT NULL,
    prdt_type_cd TEXT NULL,
    status_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_instrument_status_snapshot_source_type
        CHECK (source_type IN ('kis_stock_basic_info', 'kis_inquire_price', 'composed_status')),
    CONSTRAINT chk_instrument_status_snapshot_status_scope
        CHECK (status_scope IN ('instrument', 'market_overlay_probe', 'submit_preflight'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_status_snapshots_natural_key
    ON trading.instrument_status_snapshots (instrument_id, snapshot_at, source_type, status_scope);

CREATE INDEX IF NOT EXISTS idx_instrument_status_snapshots_instrument_snapshot
    ON trading.instrument_status_snapshots (instrument_id, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_instrument_status_snapshots_source_snapshot
    ON trading.instrument_status_snapshots (source_type, snapshot_at DESC);

COMMENT ON TABLE trading.instrument_status_snapshots IS
    'CTPF1002R 및 시세 응답 기반 종목 상태 snapshot fact. instrument master와 분리된 규정/거래 가능성 상태 저장소.';
