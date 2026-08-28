-- FDC 실제 dispatch deadline carryover의 프로세스 재기동 durable 복원
-- (2026-08-28 4차 리뷰 보정 — PR #359).
--
-- 설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
-- shared_13rpm_quota_design_2026-08-25.md.
--
-- ops-scheduler는 항상 `scripts.run_decision_loop --count 1`로 단발
-- 프로세스를 spawn한다 — cycle deadline 때문에 완결하지 못한 job을
-- 프로세스 메모리(cross-cycle carryover)에만 남기면, 그 프로세스가
-- cycle 종료 직후 종료돼 carryover가 그대로 사라진다. 다음 invocation
-- (새 프로세스)이 이 job을 안전하게 재개하려면, EI/AR/AC 결과(pre_fdc
-- 단계 산출물)와 correlation_id가 DB에 durable하게 남아 있어야 한다.
--
-- `pre_fdc_result_json`은 이미 pre_fdc subprocess가 산출한 JSON-safe
-- dict(EventInterpretation/AIRisk/AICompliance 출력 + FDC dispatch 필요
-- 여부 판정만 담는다 — position/cash/risk snapshot 등 시간에 따라
-- 낡을 수 있는 값은 저장하지 않는다. 재개 시 override/EV-gate/sizing/
-- submit 단계는 항상 그 시점에 새로 조회한 context로 다시 계산되므로
-- (기존 `precomputed_agent_bundle` 경로), 오래된 context를 굳이 durable
-- 하게 들고 있을 필요가 없다 — 최소 범위 원칙에 따라 두 컬럼만 추가한다.

BEGIN;

ALTER TABLE trading.fdc_queue_jobs
    ADD COLUMN IF NOT EXISTS pre_fdc_result_json JSONB,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT;

COMMENT ON COLUMN trading.fdc_queue_jobs.pre_fdc_result_json IS
    'pre_fdc(EI/AR/AC) subprocess 산출물 — 프로세스 재기동 후 durable '
    'resume에 필요한 최소 정보만 담는다. status=QUEUED인 real job은 '
    '항상 이 값이 채워져 있다(register_real_job()이 pre_fdc 완료 '
    '직후에만 호출되므로).';

COMMENT ON COLUMN trading.fdc_queue_jobs.correlation_id IS
    'pre_fdc 단계가 쓴 correlation_id — 재개 시 fdc_only subprocess '
    'payload와 audit trail을 원래 결정 사이클과 연결하기 위해 보존한다.';

COMMIT;
