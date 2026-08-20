-- policy_git_sha 컬럼 추가 — Stage A(정책평가 인프라 로깅 계약 보강,
-- 2026-08-20) 1차 구현 단위 A-2.
-- 설계 근거: docs/40_action_plans/post_sppv3_policy_evaluation_design_
-- 2026-08-20.md §11.5.
--
-- 현재는 어떤 결정/스킵이 어떤 코드 버전에서 나왔는지 DB만으로 추적할
-- 방법이 없다(``config_versions``는 3행뿐이고, 설정값 버전 관리용이라
-- gate/threshold 코드 로직 변경을 추적하는 용도가 아니다). 이 두 컬럼은
-- 결정을 만든 코드의 git commit SHA를 관측성 전용으로 남긴다 — 판정
-- 로직에는 전혀 영향을 주지 않으며, nullable이라 값이 없으면 기존과
-- 동일하게 동작한다(하위 호환).
--
-- trade_decisions와 guardrail_evaluations 양쪽에 동일한 컬럼명으로
-- 남기는 이유: 정상적으로 생성된 결정(trade_decisions)과 스킵된
-- 결정(guardrail_evaluations)을 같은 정책 버전 기준으로 함께 조회할
-- 수 있어야 하기 때문이다.

ALTER TABLE trading.trade_decisions
    ADD COLUMN policy_git_sha VARCHAR(64);

ALTER TABLE trading.guardrail_evaluations
    ADD COLUMN policy_git_sha VARCHAR(64);
