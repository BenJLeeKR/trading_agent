-- decision_cycle_id 컬럼 추가 — Stage A(정책평가 인프라 로깅 계약
-- 보강, 2026-08-20) 1차 구현 단위 A-1b.
-- 설계 근거: docs/40_action_plans/post_sppv3_policy_evaluation_design_
-- 2026-08-20.md §13.
--
-- 지금까지 guardrail_evaluations에 남는 pre-AI gate 스킵/Pass 2
-- general lane drop 기록은 어느 decision cycle에서 발생했는지를 묶어
-- 조회할 방법이 없었다(decision_context_id/trade_decision_id가
-- 이 경로들에서는 항상 NULL). 이 컬럼은 관측성 전용 cycle 식별자를
-- 저장한다 — 판정 로직에는 전혀 영향을 주지 않으며, nullable이라
-- 값이 없으면(수동/단독 실행 등) 기존과 동일하게 동작한다(하위 호환).
--
-- 이번 턴 범위는 guardrail_evaluations authoritative contract 보강
-- 뿐이다 — trade_decisions는 decision_context_id 자체가 이미 cycle
-- 단위 조인에 충분해(정상 생성된 결정은 애초에 decision_context_id가
-- NULL이 아님) 이번 마이그레이션에 포함하지 않는다.

ALTER TABLE trading.guardrail_evaluations
    ADD COLUMN decision_cycle_id VARCHAR(128);
