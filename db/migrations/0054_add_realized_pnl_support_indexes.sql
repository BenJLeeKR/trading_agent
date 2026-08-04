-- 0053에서 추가한 realized PnL ledger 테이블에 대한 비파괴적 보조 인덱스.
-- 기존 테이블(order_requests)에는 신규 access path 1건만 보강한다.
-- fill_events에 대한 추가 인덱스는 넣지 않는다 — 이미 존재하는
-- idx_fill_events_broker_order_time (broker_order_id, fill_timestamp DESC)
-- (db/migrations/0001_initial_schema.sql:458-459)와 90% 이상 겹치고,
-- btree 인덱스는 역방향(ASC) 스캔도 동일 비용으로 지원하므로 방향 차이가
-- 별도 인덱스를 정당화하지 않는다. 근거는
-- docs/40_action_plans/kis_realized_pnl_moving_average_action_plan.md의
-- 부록(본 migration과 함께 작성한 설계 메모) 참고.

-- ── realized_pnl_computation_runs ──
-- trading.fill_sync_runs(0029)와 동일하게 단일 컬럼 인덱스 2개로 분리한다.
-- (started_at DESC, status) 복합 인덱스 하나보다, status만으로 필터링하는
-- 조회(예: 실패한 run만 조회)를 별도로 지원할 수 있어 기존 관례와도 맞는다.
CREATE INDEX IF NOT EXISTS idx_realized_pnl_computation_runs_started_at
    ON trading.realized_pnl_computation_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_realized_pnl_computation_runs_status
    ON trading.realized_pnl_computation_runs (status);

-- ── position_cost_basis_state ──
-- 재계산 대기 상태를 오래된 순으로 스캔하는 운영/복구 워커 쿼리를 지원한다.
CREATE INDEX IF NOT EXISTS idx_position_cost_basis_state_recompute
    ON trading.position_cost_basis_state (recompute_required, updated_at);

-- ── realized_pnl_events ──
-- 종목별 누계/체결별 조회(계좌×종목 기준, 최신순)를 지원한다.
CREATE INDEX IF NOT EXISTS idx_realized_pnl_events_account_instrument_time
    ON trading.realized_pnl_events (account_id, instrument_id, fill_timestamp DESC);

-- 주문 단위 조회(9.1절 "주문 단위" 집계)를 지원한다.
CREATE INDEX IF NOT EXISTS idx_realized_pnl_events_order_request_time
    ON trading.realized_pnl_events (order_request_id, fill_timestamp DESC);

-- 특정 computation_run이 생성한 이벤트 조회(운영 검증/디버깅) — realtime
-- run 단위 결과 확인, 백필 run 결과 검증에 사용한다.
CREATE INDEX IF NOT EXISTS idx_realized_pnl_events_computation_run
    ON trading.realized_pnl_events (computation_run_id);

-- ── realized_pnl_recompute_queue ──
-- 미해결(resolved_at IS NULL) 항목을 요청 시각 순으로 소진하는 복구 워커
-- 쿼리를 지원한다.
CREATE INDEX IF NOT EXISTS idx_realized_pnl_recompute_queue_pending
    ON trading.realized_pnl_recompute_queue (resolved_at, requested_at);

-- ── 기존 테이블 보강: order_requests ──
-- account_id + status + submitted_at 인덱스(0001)는 이미 있으나, 계좌×종목
-- 단위로 order_requests를 찾아 broker_orders/fill_events를 역추적하는
-- ledger 쪽 access path는 아직 지원되지 않는다. 비파괴적 추가 인덱스다.
CREATE INDEX IF NOT EXISTS idx_order_requests_account_instrument
    ON trading.order_requests (account_id, instrument_id, order_request_id);
