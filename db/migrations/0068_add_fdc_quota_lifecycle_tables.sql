-- FDC cycle-scoped batch queue + Gemini 공용 13 RPM quota — Phase 1
-- lifecycle shadow 기반 스키마.
--
-- 설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
-- shared_13rpm_quota_design_2026-08-25.md §8(영속 스키마).
--
-- 이번 마이그레이션은 신규 테이블 3개만 추가한다 — 기존 테이블/컬럼은
-- 전혀 건드리지 않으며, 이 스키마 자체는 어떤 기존 런타임 경로에도
-- 아직 연결되지 않는다(Phase 1: shadow 관측 전용, 실제 quota enforcement
-- 아님). `mode` 컬럼('shadow'|'real')으로 향후 실제 dispatcher 전환 시의
-- 통계와 이번 shadow 관측 값이 섞이지 않도록 분리한다.

BEGIN;

-- ── fdc_quota_state: singleton anchor 행 ────────────────────────────────
-- "최근 reservation 행"이 아니라 "항상 존재하는 고정 행"을 SELECT ... FOR
-- UPDATE로 잠가야 phantom insert 경쟁 조건이 발생하지 않는다(설계 문서
-- §6). 이 테이블은 quota_scope당 정확히 1행만 갖는다.
CREATE TABLE IF NOT EXISTS trading.fdc_quota_state (
    quota_scope TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO trading.fdc_quota_state (quota_scope)
VALUES ('gemini:shared-operational')
ON CONFLICT (quota_scope) DO NOTHING;

-- ── fdc_queue_jobs: FDC batch job의 최신 상태(설계 문서 §8) ─────────────
CREATE TABLE IF NOT EXISTS trading.fdc_queue_jobs (
    job_id UUID PRIMARY KEY,
    decision_cycle_id TEXT,
    decision_context_id UUID,
    symbol VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    mode TEXT NOT NULL DEFAULT 'real' CHECK (mode IN ('shadow', 'real')),
    status TEXT NOT NULL,
    queue_poll_count INTEGER NOT NULL DEFAULT 0,
    reservation_denied_count INTEGER NOT NULL DEFAULT 0,
    dispatch_attempt_no INTEGER NOT NULL DEFAULT 0,
    provider_retry_count INTEGER NOT NULL DEFAULT 0,
    pre_http_execution_failure_count INTEGER NOT NULL DEFAULT 0,
    queue_reenqueue_count INTEGER NOT NULL DEFAULT 0,
    permit_consumed_count INTEGER NOT NULL DEFAULT 0,
    http_attempt_count INTEGER NOT NULL DEFAULT 0,
    http_429_count INTEGER NOT NULL DEFAULT 0,
    reserved_but_http_not_started_count INTEGER NOT NULL DEFAULT 0,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    trade_decision_id UUID REFERENCES trading.trade_decisions (trade_decision_id),
    failure_or_cancel_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fdc_queue_jobs_status
    ON trading.fdc_queue_jobs (status);

CREATE INDEX IF NOT EXISTS idx_fdc_queue_jobs_decision_cycle_id
    ON trading.fdc_queue_jobs (decision_cycle_id);

-- ── fdc_provider_attempts: append-only, reservation 1회=attempt 1행 ─────
-- job_id는 nullable — 비운영 수동 호출(설계 문서 §11 A안)은 fdc_queue_jobs
-- row 자체를 만들지 않고 manual_run_id로만 연결한다.
CREATE TABLE IF NOT EXISTS trading.fdc_provider_attempts (
    attempt_id UUID PRIMARY KEY,
    job_id UUID REFERENCES trading.fdc_queue_jobs (job_id),
    manual_run_id TEXT,
    quota_scope TEXT NOT NULL,
    caller_id TEXT NOT NULL,
    queue_entry_id TEXT,
    mode TEXT NOT NULL DEFAULT 'real' CHECK (mode IN ('shadow', 'real')),
    attempt_no INTEGER NOT NULL,
    provider_retry_count INTEGER NOT NULL DEFAULT 0,
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    outcome TEXT NOT NULL,
    http_status INTEGER,
    error_class TEXT,
    http_429_observed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- job_id가 있는(운영 FDC) attempt만 (job_id, attempt_no) 유일성을 강제한다
-- — 수동 호출(job_id NULL)은 이 제약 대상이 아니다(설계 문서 §8).
CREATE UNIQUE INDEX IF NOT EXISTS uq_fdc_provider_attempts_job_attempt
    ON trading.fdc_provider_attempts (job_id, attempt_no)
    WHERE job_id IS NOT NULL;

-- sliding-window(quota_scope, reserved_at) 조회 전용 인덱스 — 설계 문서
-- §14의 self-join 기반 감사 SQL과 실제 reservation 판단 SQL(§6) 양쪽이
-- 이 인덱스를 탄다. mode를 선두에 두어 실제(real) 집계 쿼리가 shadow
-- 행을 스캔하지 않도록 한다.
CREATE INDEX IF NOT EXISTS idx_fdc_provider_attempts_mode_scope_reserved_at
    ON trading.fdc_provider_attempts (mode, quota_scope, reserved_at);

CREATE INDEX IF NOT EXISTS idx_fdc_provider_attempts_job_id
    ON trading.fdc_provider_attempts (job_id);

COMMIT;
