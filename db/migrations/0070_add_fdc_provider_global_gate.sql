-- FDC provider 전체(legacy mode="full" + held_position/BUY actual-
-- dispatch) 실제 HTTP 시작 건수를 하나의 durable global gate로 통제하기
-- 위한 신규 테이블(PR D, 2026-09-03).
--
-- 설계 근거: docs/40_action_plans/fdc_pr_d_provider_global_quota_design_
-- 2026-09-02.md (대안 C — 별도 global HTTP-start gate 신설).
--
-- 기존 fdc_quota_state/fdc_provider_attempts/fdc_queue_jobs를 재사용하지
-- 않는 이유: 그 테이블들의 window count SQL(fdc_quota.py try_reserve())은
-- quota_scope 전체를 mode='real'로 필터링해 집계한다. legacy 호출을 같은
-- 테이블에 caller_id만 다르게 기록하면, actual coordinator 자신의 FIFO/
-- window 판정(held_position/BUY 레인 사이의 공정성)에 legacy 트래픽이
-- 섞여 들어가 "global gate 내부 상태와 actual coordinator의 reservation/
-- window 상태는 서로 독립적이다"라는 계약이 깨진다. 따라서 완전히 별도의
-- singleton anchor + append-only grant 로그를 신설한다.

BEGIN;

-- ── fdc_provider_global_gate_state: singleton anchor 행 ─────────────────
-- fdc_quota_state와 동일한 패턴 — "항상 존재하는 고정 행"을 SELECT ...
-- FOR UPDATE로 잠가야 phantom insert 경쟁 조건 없이 window count를
-- 원자적으로 판단할 수 있다. gate_scope당 정확히 1행만 갖는다.
CREATE TABLE IF NOT EXISTS trading.fdc_provider_global_gate_state (
    gate_scope TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO trading.fdc_provider_global_gate_state (gate_scope)
VALUES ('gemini:provider-global')
ON CONFLICT (gate_scope) DO NOTHING;

-- ── fdc_provider_global_gate_grants: append-only grant 기록 ──────────────
-- grant 시점(HTTP 실제 시작 여부와 무관)에 정확히 1행이 INSERT된다 —
-- 환불(DELETE/UPDATE로 이 행을 없애는 동작)은 존재하지 않는다(보수적
-- 소비 규칙 — grant 후 HTTP 시작 전에 실패해도 이 행은 그대로 남아
-- window에 계속 반영된다). caller_lane은 관측용("legacy"|"actual")이며
-- window 판정 자체는 caller_lane과 무관하게 gate_scope 전체를 합산한다.
CREATE TABLE IF NOT EXISTS trading.fdc_provider_global_gate_grants (
    grant_id UUID PRIMARY KEY,
    gate_scope TEXT NOT NULL,
    caller_lane TEXT NOT NULL,
    caller_id TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fdc_provider_global_gate_grants_scope_time
    ON trading.fdc_provider_global_gate_grants (gate_scope, granted_at);

COMMIT;
