BEGIN;

-- ============================================================================
-- Migration 0014: Add market_session tables for P2 scheduler hardening
--
-- Creates:
--   trading.market_sessions   — 장운영 세션 상태 (run_date 기준 upsert)
--   trading.session_events    — 장운영 phase 변경 이벤트 로그 (append-only)
--
-- Depends on: trading schema (created in 0001)
-- ============================================================================

-- --------------------------------------------------------------------------
-- 1. trading.market_sessions
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.market_sessions (
    id              BIGSERIAL       PRIMARY KEY,
    run_date        DATE            NOT NULL,
    is_trading_day  BOOLEAN         NOT NULL,
    opnd_yn         VARCHAR(4)      NULL,
    bzdy_yn         VARCHAR(4)      NULL,
    tr_day_yn       VARCHAR(4)      NULL,
    market_phase    VARCHAR(20)     NULL,
    raw_opnd_yn     VARCHAR(4)      NULL,
    raw_mkop_cls_code   VARCHAR(4)  NULL,
    raw_antc_mkop_cls_code VARCHAR(4) NULL,
    source          VARCHAR(64)     NOT NULL DEFAULT 'unknown',
    reason          VARCHAR(256)    NULL,
    checked_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_sessions_run_date
    ON trading.market_sessions (run_date);

CREATE INDEX IF NOT EXISTS idx_market_sessions_checked_at
    ON trading.market_sessions (checked_at DESC);

COMMENT ON TABLE  trading.market_sessions IS '장운영 세션 상태 — run_date 기준 1행, P2 scheduler가 주기적으로 upsert';
COMMENT ON COLUMN trading.market_sessions.run_date IS '기준일 (KST)';
COMMENT ON COLUMN trading.market_sessions.is_trading_day IS '거래일 여부 (076 opnd_yn)';
COMMENT ON COLUMN trading.market_sessions.opnd_yn IS '076 원본 운영여부코드';
COMMENT ON COLUMN trading.market_sessions.bzdy_yn IS '076 원본 영업일코드';
COMMENT ON COLUMN trading.market_sessions.tr_day_yn IS '076 원본 거래일코드';
COMMENT ON COLUMN trading.market_sessions.market_phase IS '163 실시간 장운영구분 (PRE_MARKET, OPEN, CLOSING, AFTER_HOURS, HALT, UNKNOWN)';
COMMENT ON COLUMN trading.market_sessions.raw_opnd_yn IS '076 API 응답의 opnd_yn 원본 값';
COMMENT ON COLUMN trading.market_sessions.raw_mkop_cls_code IS '163 WebSocket 응답의 mkop_cls_code 원본 값';
COMMENT ON COLUMN trading.market_sessions.raw_antc_mkop_cls_code IS '163 WebSocket 응답의 antc_mkop_cls_code 원본 값';
COMMENT ON COLUMN trading.market_sessions.source IS 'session 정보 출처 (kis_076, kis_163, combined, fallback)';
COMMENT ON COLUMN trading.market_sessions.reason IS '부가 설명 (휴장 사유 등)';
COMMENT ON COLUMN trading.market_sessions.checked_at IS '마지막 확인 시각 (KST)';

-- --------------------------------------------------------------------------
-- 2. trading.session_events
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading.session_events (
    id              BIGSERIAL       PRIMARY KEY,
    market_session_id  BIGINT       NOT NULL
                        REFERENCES trading.market_sessions(id)
                        ON DELETE CASCADE,
    previous_phase  VARCHAR(20)     NULL,
    new_phase       VARCHAR(20)     NOT NULL,
    trigger_source  VARCHAR(64)     NULL,
    metadata        JSONB           NULL,
    occurred_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_events_session_id
    ON trading.session_events (market_session_id);

CREATE INDEX IF NOT EXISTS idx_session_events_occurred_at
    ON trading.session_events (occurred_at DESC);

COMMENT ON TABLE  trading.session_events IS '장운영 phase 변경 이벤트 로그 (append-only)';
COMMENT ON COLUMN trading.session_events.market_session_id IS '참조하는 market_sessions.id';
COMMENT ON COLUMN trading.session_events.previous_phase IS '변경 전 phase (null=최초)';
COMMENT ON COLUMN trading.session_events.new_phase IS '변경 후 phase';
COMMENT ON COLUMN trading.session_events.trigger_source IS '이벤트 발생 원인 (websocket_163, scheduler, manual)';
COMMENT ON COLUMN trading.session_events.metadata IS '추가 메타데이터 (JSONB)';

COMMIT;
