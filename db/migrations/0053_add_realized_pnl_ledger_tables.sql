-- 이동평균법 실현 손익(Realized PnL) ledger 신규 테이블 5종.
-- 설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md
-- 실행 계획: docs/40_action_plans/kis_realized_pnl_moving_average_action_plan.md
--
-- 이 migration은 신규 테이블만 추가한다. 기존 fill_events/order_requests/
-- broker_orders/position_snapshots 컬럼은 변경하지 않는다.
-- 보조 인덱스는 0054_add_realized_pnl_support_indexes.sql로 분리한다.

CREATE TABLE IF NOT EXISTS trading.realized_pnl_computation_runs (
    computation_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type VARCHAR(32) NOT NULL,
    account_id UUID REFERENCES trading.accounts (account_id),
    status VARCHAR(32) NOT NULL,
    fills_applied INTEGER NOT NULL DEFAULT 0,
    fills_skipped_duplicate INTEGER NOT NULL DEFAULT 0,
    fills_replayed INTEGER NOT NULL DEFAULT 0,
    anomalies_detected INTEGER NOT NULL DEFAULT 0,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_realized_pnl_computation_runs_run_type
        CHECK (run_type IN ('realtime_incremental', 'backfill_replay')),
    CONSTRAINT ck_realized_pnl_computation_runs_status
        CHECK (status IN ('running', 'completed', 'partial', 'failed'))
);

-- 계좌×종목 단위 이동평균 상태(가변). PK 자체가 "종목당 1행"을 강제한다.
CREATE TABLE IF NOT EXISTS trading.position_cost_basis_state (
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    quantity NUMERIC(24, 8) NOT NULL,
    average_cost NUMERIC(20, 8) NOT NULL,
    last_applied_fill_event_id UUID REFERENCES trading.fill_events (fill_event_id),
    last_applied_fill_timestamp TIMESTAMPTZ,
    recompute_required BOOLEAN NOT NULL DEFAULT FALSE,
    recompute_reason VARCHAR(64),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, instrument_id),
    -- 국내주식 계좌의 숏 포지션 지원 여부는 미확인 상태다(상세 설계 문서 2.1절).
    -- 이 CHECK는 "지원한다"는 결정이 아니라, 계산 엔진 버그로 음수 잔량이
    -- 조용히 저장되는 것을 DB 레벨에서 막기 위한 하드 가드다. 실제로 숏
    -- 포지션을 지원하기로 결정되면 이 제약을 별도 migration으로 완화한다.
    CONSTRAINT ck_position_cost_basis_state_quantity_non_negative
        CHECK (quantity >= 0)
);

-- 매도 체결 기준 append-only 실현 손익 원장. UPDATE/DELETE를 전제하지 않고
-- superseded_by_event_id self-reference로만 정정한다(상세 설계 문서 7.3절).
CREATE TABLE IF NOT EXISTS trading.realized_pnl_events (
    realized_pnl_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    fill_event_id UUID NOT NULL REFERENCES trading.fill_events (fill_event_id),
    broker_order_id UUID NOT NULL REFERENCES trading.broker_orders (broker_order_id),
    order_request_id UUID NOT NULL REFERENCES trading.order_requests (order_request_id),
    sell_quantity NUMERIC(24, 8) NOT NULL,
    sell_price NUMERIC(20, 8) NOT NULL,
    avg_cost_basis_before NUMERIC(20, 8) NOT NULL,
    fee NUMERIC(20, 8) NOT NULL DEFAULT 0,
    tax NUMERIC(20, 8) NOT NULL DEFAULT 0,
    fee_tax_source VARCHAR(16) NOT NULL,
    realized_pnl_gross NUMERIC(20, 8) NOT NULL,
    realized_pnl_net NUMERIC(20, 8) NOT NULL,
    position_quantity_after NUMERIC(24, 8) NOT NULL,
    computation_run_id UUID NOT NULL REFERENCES trading.realized_pnl_computation_runs (computation_run_id),
    superseded_by_event_id UUID REFERENCES trading.realized_pnl_events (realized_pnl_event_id),
    fill_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_realized_pnl_events_fill_event UNIQUE (fill_event_id),
    CONSTRAINT ck_realized_pnl_events_fee_tax_source
        CHECK (fee_tax_source IN ('reported', 'assumed_zero')),
    CONSTRAINT ck_realized_pnl_events_sell_quantity
        CHECK (sell_quantity > 0),
    CONSTRAINT ck_realized_pnl_events_sell_price
        CHECK (sell_price >= 0)
);

-- 조회 성능용 일자 집계 캐시. realized_pnl_events에서 언제든 재생성 가능한
-- 파생 데이터이며 진실의 원천이 아니다(상세 설계 문서 4.3절).
CREATE TABLE IF NOT EXISTS trading.realized_pnl_daily_aggregates (
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    trade_date DATE NOT NULL,
    realized_pnl_net_sum NUMERIC(20, 8) NOT NULL DEFAULT 0,
    sell_event_count INTEGER NOT NULL DEFAULT 0,
    computation_run_id UUID NOT NULL REFERENCES trading.realized_pnl_computation_runs (computation_run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, instrument_id, trade_date)
);

-- ledger 갱신 실패 / out-of-order fill / anomaly 재계산 큐(상세 설계 문서 8절).
-- "fill 저장 성공 후 ledger 실패"를 조용히 넘기지 않기 위한 관측 가능한 복구 계약.
CREATE TABLE IF NOT EXISTS trading.realized_pnl_recompute_queue (
    recompute_queue_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES trading.accounts (account_id),
    instrument_id UUID NOT NULL REFERENCES trading.instruments (instrument_id),
    reason_code VARCHAR(64) NOT NULL,
    triggering_fill_event_id UUID REFERENCES trading.fill_events (fill_event_id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by_computation_run_id UUID REFERENCES trading.realized_pnl_computation_runs (computation_run_id),
    CONSTRAINT ck_realized_pnl_recompute_queue_reason_code
        CHECK (reason_code IN (
            'ledger_write_failed',
            'out_of_order_fill_detected',
            'anomaly_negative_quantity',
            'manual_request'
        ))
);
