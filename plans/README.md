# Plans Index

`plans/` 디렉터리는 구현 진행 과정에서 작성된 작업 계획, 검토 보고서, 후속 수정 계획을 **오래된 순서부터 최신 순서까지** 정리한 기록이다.

## 문서 관리 원칙

- **하나의 plan 번호 = 하나의 canonical 파일**: 같은 작업 단위에 대해 여러 버전의 plan 문서를 파일로 분리하지 않는다. 수정 이력이 필요한 경우, 문서 내부 `Revision History` 섹션에 누적 기록한다. 같은 task의 원본안/수정안/후속안을 별도 파일로 쪼개지 않는다.
- **파일명**: 숫자 접두사 + 설명으로 구성 (예: `04.xxx.md`, `29_ai_decision_backend_contract.md`). 엄격한 패턴보다는 `plans/README.md` 목록에서 순서대로 식별 가능하게 하는 것이 목적이다.
- **Rejected 접근법**: 문서 내 `부록(Appendix)` 섹션에 참고용으로 보관한다. 별도 파일로 분리하지 않는다.
- **Backlog 관리**: "지금 당장 실행할 작업"은 numbered plan으로, "나중에 할 작업"은 [`BACKLOG.md`](./BACKLOG.md)에 기록한다. 실행할 때만 번호 Plan을 생성하고, 아직 시작하지 않을 작업은 BACKLOG에만 기록한다. BACKLOG 항목이 실제로 시작되면 해당 항목을 완료 표시하고 새 numbered plan으로 승격한다.
- **참조**: [`plans/BACKLOG.md`](./BACKLOG.md) — Future work candidates 정리

권장 읽기 방식:

1. 처음부터 전체 흐름을 따라가려면 `01`부터 순서대로 읽는다.
2. 현재 상태만 빠르게 파악하려면 `18` 이후 문서부터 읽는다.
3. 특정 milestone의 맥락이 필요할 때만 그 이전 문서로 내려간다.
4. **아직 실행하지 않은 작업 아이디어**는 [`BACKLOG.md`](./BACKLOG.md)를 참조한다.

## 문서 목록

| 순서 | 파일 | 설명 |
|------|------|------|
| 01 | [`01.dev_infrastructure_plan.md`](./01.dev_infrastructure_plan.md) | 초기 개발 인프라, Docker, DB, pyproject, Makefile 구성 계획 |
| 02 | [`02.mvp_milestone1_implementation_plan.md`](./02.mvp_milestone1_implementation_plan.md) | MVP Milestone 1 구현 계획 |
| 03 | [`03.milestone1_completion_review.md`](./03.milestone1_completion_review.md) | Milestone 1 완료 검토 및 PostgreSQL 통합 확인 |
| 04 | [`04.milestone2_implementation_plan.md`](./04.milestone2_implementation_plan.md) | Postgres 기반 audit, repository, paper loop 안정화 계획 |
| 05 | [`05.milestone2_optimistic_locking.md`](./05.milestone2_optimistic_locking.md) | 주문 상태 전이 optimistic locking 설계 |
| 06 | [`06.milestone3_implementation_plan.md`](./06.milestone3_implementation_plan.md) | Milestone 3 구현 계획 |
| 07 | [`07.document_code_alignment_report.md`](./07.document_code_alignment_report.md) | 설계 문서와 코드 간 gap 분석 보고서 |
| 08 | [`08.milestone4_safe_order_path_persistence.md`](./08.milestone4_safe_order_path_persistence.md) | 안전한 주문 경로 persistence 정렬 계획 |
| 09 | [`09.milestone5_decision_persistence_alignment.md`](./09.milestone5_decision_persistence_alignment.md) | decision persistence 구조 정렬 계획 |
| 10 | [`10.milestone6_broker_contract_reconciliation_alignment.md`](./10.milestone6_broker_contract_reconciliation_alignment.md) | broker contract / reconciliation 정렬 계획 |
| 11 | [`11.milestone6_post_fix_items.md`](./11.milestone6_post_fix_items.md) | Milestone 6 후속 수정 항목 |
| 12 | [`12.milestone7_broker_capacity_and_event_data.md`](./12.milestone7_broker_capacity_and_event_data.md) | broker capacity, event data 기반 확장 계획 |
| 13 | [`13.milestone7_fixes_plan.md`](./13.milestone7_fixes_plan.md) | Milestone 7 버그 수정 및 테스트 보강 계획 |
| 14 | [`14.milestone8_plan.md`](./14.milestone8_plan.md) | Milestone 8 전체 계획 |
| 15 | [`15.milestone8_event_loop_fix_plan.md`](./15.milestone8_event_loop_fix_plan.md) | Milestone 8 event loop 계약 불일치 수정 계획 |
| 16 | [`16.post_milestone8_plan.md`](./16.post_milestone8_plan.md) | Milestone 8 이후 warning/smoke 후속 작업 계획 |
| 17 | [`17.fix_audit_log_ordering_plan.md`](./17.fix_audit_log_ordering_plan.md) | audit log ordering deterministic fix 계획 |
| 18 | [`18.three_priority_tasks_plan.md`](./18.three_priority_tasks_plan.md) | 이후 우선순위 3개 작업 계획 |
| 19 | [`19.priority_5_prerequisite_schema_alignment.md`](./19.priority_5_prerequisite_schema_alignment.md) | AI agent schema alignment 선행 계획 |
| 20 | [`20.fix_decision_context_id_semantic_mismatch.md`](./20.fix_decision_context_id_semantic_mismatch.md) | `decision_context_id` payload/storage 의미 분리 계획 |
| 21 | [`21.priority_5_1_deepseek_provider_connection.md`](./21.priority_5_1_deepseek_provider_connection.md) | DeepSeek 기반 첫 Provider 연결 계획 |
| 22 | [`22.priority_5_1_runtime_wiring.md`](./22.priority_5_1_runtime_wiring.md) | runtime에서 real provider agent 주입 계획 |
| 23 | [`23.runtime_wiring_helper_refactor.md`](./23.runtime_wiring_helper_refactor.md) | runtime wiring helper 공통화 및 Postgres 테스트 보강 계획 |
| 24 | [`24.llm_provider_resolver.md`](./24.llm_provider_resolver.md) | LLM_PROVIDER 기반 env resolver 일반화 계획 |
| 25 | [`25_runtime_event_interpretation_smoke.md`](./25_runtime_event_interpretation_smoke.md) | Runtime EventInterpretationAgent smoke 검증 계획 |
| 26 | [`26_real_ai_risk_agent.md`](./26_real_ai_risk_agent.md) | Real AIRiskAgent 구현 계획 (schema 공유, bootstrap wiring, orchestrator 통합) |
| 27 | [`27_ei_output_to_ai_risk_flow.md`](./27_ei_output_to_ai_risk_flow.md) | EI 출력 -> AIRiskAgent 전달 설계 변경 계획 |
| 28 | [`28_real_final_decision_composer_agent.md`](./28_real_final_decision_composer_agent.md) | Real FinalDecisionComposerAgent 구현 계획 (EI→AR→FDC 데이터 흐름 완성) |
| 29 | [`29_ai_decision_backend_contract.md`](./29_ai_decision_backend_contract.md) | AI Decision Backend Contract — `AIDecisionInputs` 정규화된 backend 계약 (Rev 1 REJECTED, Rev 2 IMPLEMENTED, Rev 3 IMPLEMENTED) |
| 30 | [`30_runtime_three_agent_smoke.md`](./30_runtime_three_agent_smoke.md) | Real 3-Agent Runtime Smoke Verification — EI→AR→FDC full chain smoke, env-isolated fallback, provider-agnostic skip (Rev 2: env 제어 정렬) |
| 31 | [`31_ai_risk_input_expansion.md`](./31_ai_risk_input_expansion.md) | AIRiskAgent input expansion: richer deterministic account/risk context (position, cash, risk_limit snapshots) + PG repos + prompt summaries |
| 32 | [`32_ai_broker_boundary_pre_submit_verification.md`](./32_ai_broker_boundary_pre_submit_verification.md) | AI-Broker Pre-Submit Safety Boundary Verification: AI layer가 execution boundary를 우회하지 않음을 테스트로 증명 |
| 33 | [`33_post_submit_reconciliation_boundary.md`](./33_post_submit_reconciliation_boundary.md) | Post-Submit Unknown State / Reconciliation Boundary Verification: submit 이후 ambiguous/unknown 상태에서 reconciliation-first 원칙 검증 + event loop dedup bug fix |
| 34 | [`34_reconcile_required_fill_transition_policy.md`](./34_reconcile_required_fill_transition_policy.md) | RECONCILE_REQUIRED → FILLED 차단 정책: WS fill notification 중 optimistic state progression 방지. Fill data 보존, state는 reconciliation까지 hold. State machine hard boundary + event loop explicit guard. |
| 35 | [`35_reconciliation_authoritative_state_reflection.md`](./35_reconciliation_authoritative_state_reflection.md) | Reconciliation Authoritative State Reflection: broker inquiry 결과를 local order state에 안전하게 반영. `transition_to_authoritative()` 전용 경로로 `_ALLOWED_TRANSITIONS` 불변 유지. 실패 시 `reflection_failed` + lock 유지. |
| 36 | [`36_kis_paper_ai_runtime_smoke.md`](./36_kis_paper_ai_runtime_smoke.md) | KIS Paper + AI Layer Combined Runtime Smoke Verification: AI layer 3-agent chain + KIS paper adapter가 결합된 runtime에서 execution boundary 안전성 검증. 3 scenarios (Runtime Wiring, Assemble Compatibility, Minimal Paper Submit) |
| 37 | [`37_long_path_end_to_end_integration.md`](./37_long_path_end_to_end_integration.md) | Long-Path End-to-End Integration Scenario: AI assemble -> create_order -> submit (uncertain) -> reconciliation -> authoritative reflection -> final state. KIS 불필요. In-memory + Postgres + Failure branch. |
| 38 | [`38_postgres_long_path_execution.md`](./38_postgres_long_path_execution.md) | Postgres-backed Long-Path E2E Execution & Verification: env alignment (POSTGRES_URL -> DATABASE_HOST), Postgres scenario activation, persistence artifact verification in actual DB, MCP/Codex access documentation. |
| 39 | [`39_trade_decision_schema_alignment.md`](./39_trade_decision_schema_alignment.md) | Trade Decision Schema Alignment: migration 0009 (decision column nullable), Postgres persistence test for trade_decisions, zero existing test changes. |
| 40 | [`40_fastapi_inspection_api.md`](./40_fastapi_inspection_api.md) | FastAPI Inspection / Admin API (Read-Only First): Phase 1 — 9 inspection endpoints with Swagger UI, in-memory-first, 명시적 repository 주입, 최소 read model Pydantic schema. |
| 41 | [`41_inspection_api_manual_verification.md`](./41_inspection_api_manual_verification.md) | Inspection API Manual Verification Guide / Operator Checklist: Swagger UI 기반 7가지 운영 체크리스트 시나리오, 10개 endpoint별 확인 포인트, curl 명령어 모음, 현재 한계 및 다음 단계 연결. |
| 42 | [`42_postgres_backed_inspection_api_mode.md`](./42_postgres_backed_inspection_api_mode.md) | Postgres-backed Inspection API Mode (Rev 2): `create_app(runtime_mode="postgres")`로 실제 DB 데이터 조회. Pool-only lifespan + request-scoped repos. `/health`/`/readyz` DB probe 개선. Postgres API 테스트 4개. 기존 in-memory 회귀 방지. |
| 43 | [`43_containerize_inspection_api.md`](./43_containerize_inspection_api.md) | Containerize FastAPI Inspection API and docker-compose Integration: `api` 서비스 추가 (uvicorn --factory, Postgres mode, port 8000, healthcheck). `app` 서비스 유지. `create_app_from_env()` factory 함수. Makefile docker-api targets. |
| 44 | [`44_postgres_reconciliation_locks_inspection.md`](./44_postgres_reconciliation_locks_inspection.md) | Postgres-backed Reconciliation Locks Inspection Support: `list_locks()` contract 추가, InMemory + Postgres 구현, route refactor (fallback 제거), `BlockingLockEntity`, `BlockingLockStatus` 확장, test suite (in-memory + Postgres 통합). |
| 45 | [`45_inspection_api_phase2.md`](./45_inspection_api_phase2.md) | Inspection API Phase 2: accounts, clients, instruments, positions, cash-balances, broker-orders endpoint 추가. P0/P1 분류, Pydantic schema, route 파일, in-memory + Postgres 테스트. |
| 46 | [`46_auth_rbac_inspection_api.md`](./46_auth_rbac_inspection_api.md) | Auth/RBAC for Inspection API: Static Bearer token, viewer/admin RBAC, public/protected endpoint 정책, router-level dependency, OpenAPI BearerAuth scheme, safe default (auth_enabled=True). |
| 47 | [`47_auth_policy_hardening.md`](./47_auth_policy_hardening.md) | Auth Policy Hardening (Pre-UI Security Pass): Docs/OpenAPI 공개 정책 고정, Token 운영 정책 명문화, whitespace/role validation, create_app_from_env() role 전달 버그 수정, BACKLOG/README 업데이트. |
## 빠른 추천 경로

### 현재 상태만 빠르게 보기

1. [`18.three_priority_tasks_plan.md`](./18.three_priority_tasks_plan.md)
2. [`21.priority_5_1_deepseek_provider_connection.md`](./21.priority_5_1_deepseek_provider_connection.md)
3. [`22.priority_5_1_runtime_wiring.md`](./22.priority_5_1_runtime_wiring.md)
4. [`23.runtime_wiring_helper_refactor.md`](./23.runtime_wiring_helper_refactor.md)
5. [`24.llm_provider_resolver.md`](./24.llm_provider_resolver.md)
6. [`25_runtime_event_interpretation_smoke.md`](./25_runtime_event_interpretation_smoke.md)
7. [`26_real_ai_risk_agent.md`](./26_real_ai_risk_agent.md)
8. [`27_ei_output_to_ai_risk_flow.md`](./27_ei_output_to_ai_risk_flow.md)
9. [`28_real_final_decision_composer_agent.md`](./28_real_final_decision_composer_agent.md)
10. [`29_ai_decision_backend_contract.md`](./29_ai_decision_backend_contract.md)
11. [`30_runtime_three_agent_smoke.md`](./30_runtime_three_agent_smoke.md)
12. [`31_ai_risk_input_expansion.md`](./31_ai_risk_input_expansion.md)
13. [`32_ai_broker_boundary_pre_submit_verification.md`](./32_ai_broker_boundary_pre_submit_verification.md)
14. [`33_post_submit_reconciliation_boundary.md`](./33_post_submit_reconciliation_boundary.md)
15. [`34_reconcile_required_fill_transition_policy.md`](./34_reconcile_required_fill_transition_policy.md)
16. [`35_reconciliation_authoritative_state_reflection.md`](./35_reconciliation_authoritative_state_reflection.md)
17. [`36_kis_paper_ai_runtime_smoke.md`](./36_kis_paper_ai_runtime_smoke.md)
18. [`37_long_path_end_to_end_integration.md`](./37_long_path_end_to_end_integration.md)
19. [`38_postgres_long_path_execution.md`](./38_postgres_long_path_execution.md)
20. [`39_trade_decision_schema_alignment.md`](./39_trade_decision_schema_alignment.md)
21. [`40_fastapi_inspection_api.md`](./40_fastapi_inspection_api.md)
22. [`41_inspection_api_manual_verification.md`](./41_inspection_api_manual_verification.md)
23. [`42_postgres_backed_inspection_api_mode.md`](./42_postgres_backed_inspection_api_mode.md)
24. [`43_containerize_inspection_api.md`](./43_containerize_inspection_api.md)
25. [`44_postgres_reconciliation_locks_inspection.md`](./44_postgres_reconciliation_locks_inspection.md)
### AI Agent / Provider 연결 흐름만 보기

1. [`19.priority_5_prerequisite_schema_alignment.md`](./19.priority_5_prerequisite_schema_alignment.md)
2. [`20.fix_decision_context_id_semantic_mismatch.md`](./20.fix_decision_context_id_semantic_mismatch.md)
3. [`21.priority_5_1_deepseek_provider_connection.md`](./21.priority_5_1_deepseek_provider_connection.md)
4. [`22.priority_5_1_runtime_wiring.md`](./22.priority_5_1_runtime_wiring.md)
5. [`23.runtime_wiring_helper_refactor.md`](./23.runtime_wiring_helper_refactor.md)
6. [`24.llm_provider_resolver.md`](./24.llm_provider_resolver.md)
7. [`25_runtime_event_interpretation_smoke.md`](./25_runtime_event_interpretation_smoke.md)
8. [`26_real_ai_risk_agent.md`](./26_real_ai_risk_agent.md)
9. [`27_ei_output_to_ai_risk_flow.md`](./27_ei_output_to_ai_risk_flow.md)
10. [`28_real_final_decision_composer_agent.md`](./28_real_final_decision_composer_agent.md)
11. [`29_ai_decision_backend_contract.md`](./29_ai_decision_backend_contract.md)
12. [`30_runtime_three_agent_smoke.md`](./30_runtime_three_agent_smoke.md)
13. [`36_kis_paper_ai_runtime_smoke.md`](./36_kis_paper_ai_runtime_smoke.md)

### 브로커 / 실행 안전성 흐름만 보기

1. [`10.milestone6_broker_contract_reconciliation_alignment.md`](./10.milestone6_broker_contract_reconciliation_alignment.md)
2. [`12.milestone7_broker_capacity_and_event_data.md`](./12.milestone7_broker_capacity_and_event_data.md)
3. [`14.milestone8_plan.md`](./14.milestone8_plan.md)
4. [`15.milestone8_event_loop_fix_plan.md`](./15.milestone8_event_loop_fix_plan.md)
5. [`16.post_milestone8_plan.md`](./16.post_milestone8_plan.md)
6. [`17.fix_audit_log_ordering_plan.md`](./17.fix_audit_log_ordering_plan.md)
7. [`32_ai_broker_boundary_pre_submit_verification.md`](./32_ai_broker_boundary_pre_submit_verification.md)
8. [`33_post_submit_reconciliation_boundary.md`](./33_post_submit_reconciliation_boundary.md)
9. [`34_reconcile_required_fill_transition_policy.md`](./34_reconcile_required_fill_transition_policy.md)
10. [`35_reconciliation_authoritative_state_reflection.md`](./35_reconciliation_authoritative_state_reflection.md)
11. [`36_kis_paper_ai_runtime_smoke.md`](./36_kis_paper_ai_runtime_smoke.md)
12. [`37_long_path_end_to_end_integration.md`](./37_long_path_end_to_end_integration.md)
13. [`38_postgres_long_path_execution.md`](./38_postgres_long_path_execution.md)
