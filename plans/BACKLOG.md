# Backlog — Future Work Candidates

> **목적**: 번호가 부여된 실행 계획(canonical numbered plan)과 아직 착수하지 않은 작업 아이디어를 분리하여 관리한다.
>
> **원칙**: "실행할 때만 번호 Plan 생성, 아직 시작하지 않을 작업은 BACKLOG에만 기록."

---

## 관리 원칙

1. **Backlog 항목이 실제 실행으로 전환될 때**: BACKLOG.md에서 해당 항목을 `[x]`로 표시하고, 새 numbered plan을 생성한다. BACKLOG.md에는 짧게 상태 업데이트 (예: `→ Plan 41로 승격`).
2. **새로운 아이디어는 항상 BACKLOG 우선**: numbered plan에 바로 포함하지 않는다. 일단 BACKLOG에 기록하고, 실행 시점에 평가 후 승격.
3. **정기적 검토**: Plan 완료 시 BACKLOG를 검토하여 다음 우선순위를 결정한다.
4. **기존 numbered plan 문서는 건드리지 않는다**: BACKLOG.md가 future work의 단일 진실 공급원(single source of truth).

---

## Near-term (다음 1-3개 Plan 후보)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Plan 40 Phase 2 — API endpoints 확장**: `GET /orders/{id}/broker-orders`, `GET /accounts`, `GET /accounts/{id}`, `GET /clients/{id}`, `GET /instruments/{id}`, `GET /positions`, `GET /cash-balances`, `GET /guardrail-evaluations`, `GET /risk-limit-snapshots`, `GET /agent-runs` | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 2 | **Plan 40 Phase 2 — Postgres-backed API mode**: `create_app()`에 Postgres repository 주입 지원, `runtime_mode="postgres"` 모드 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 3 | **Reconciliation blocking lock list API**: `GET /reconciliation/locks` 구현을 위해 reconciliation repository에 `list_locks()` 메서드 추가. 현재 `is_blocked()`만 존재 | [Plan 40](plans/40_fastapi_inspection_api.md) | ❌ 미착수 |
| 4 | **KIS real credential + combined submit smoke**: KIS 실제 API key 확보 후 `tests/smoke/test_kis_paper_smoke.py` 등 combined submit smoke 실행 | [Plan 36](plans/36_kis_paper_ai_runtime_smoke.md) | ❌ 미착수 |
| 5 | **TradeDecisionEntity creation path**: AI agent가 `TradeDecisionEntity`를 생성할 때 `DecisionOrchestrator` → `PostgresTradeDecisionRepository.add()` 경로 구현 | [Plan 39](plans/39_trade_decision_schema_alignment.md:295) | ❌ 미착수 |

---

## Near-term (다음 1-3개 Plan 후보)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Plan 40 Phase 2 — API endpoints 확장**: `GET /orders/{id}/broker-orders`, `GET /accounts`, `GET /accounts/{id}`, `GET /clients/{id}`, `GET /instruments/{id}`, `GET /positions`, `GET /cash-balances`, `GET /guardrail-evaluations`, `GET /risk-limit-snapshots`, `GET /agent-runs` | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 2 | **Plan 40 Phase 2 — Postgres-backed API mode**: `create_app()`에 Postgres repository 주입 지원, `runtime_mode="postgres"` 모드 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ❌ 미착수 |
| 3 | **Reconciliation blocking lock list API**: `GET /reconciliation/locks` 구현을 위해 reconciliation repository에 `list_locks()` 메서드 추가. 현재 `is_blocked()`만 존재 | [Plan 40](plans/40_fastapi_inspection_api.md) | ❌ 미착수 |
| 4 | **KIS real credential + combined submit smoke**: KIS 실제 API key 확보 후 `tests/smoke/test_kis_paper_smoke.py` 등 combined submit smoke 실행 | [Plan 36](plans/36_kis_paper_ai_runtime_smoke.md) | ❌ 미착수 |
| 5 | **TradeDecisionEntity creation path**: AI agent가 `TradeDecisionEntity`를 생성할 때 `DecisionOrchestrator` → `PostgresTradeDecisionRepository.add()` 경로 구현 | [Plan 39](plans/39_trade_decision_schema_alignment.md:295) | ❌ 미착수 |
| 6 | **Docs/OpenAPI 보호 옵션 (inspection API)**: `/docs`와 `/openapi.json`을 auth 보호 대상에 포함. 현재는 공개 유지 중 | Plan 47 | ❌ 미착수 |
| 7 | **Admin UI P1 — DecisionsView detail panel**: 특정 decision 행 클릭 시 TradeDecisionDetail 또는 DecisionContextDetail 내용을 inline panel 또는 modal로 표시. 현재는 단순 리스트만 존재 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 8 | **Admin UI P1 — AccountsView filter/selection 개선**: 계좌 목록 필터 (type, strategy) 및 선택 시 상세 영역 시각적 개선 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |

## Medium-term (다음 마일스톤)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Admin UI**: 시스템 상태 모니터링, 주문/계좌 조회, 설정 관리 웹 UI | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ✅ Plan 48로 승격 |
| 2 | **Auth / RBAC for admin API**: Static Bearer token 인증, viewer/admin RBAC, public/protected endpoint 정책 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ Plan 46으로 승격 |
| 3 | **Operator intervention workflow**: 사람이 개입하여 주문 상태 강제 변경, kill switch override, 수동 reconciliation | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ❌ 미착수 |
| 4 | **Migration 0010: Drop legacy `decision` column**: `trade_decisions.decision` 컬럼 제거. Plan 39에서 nullable로 완화한 후 추가 검증 후 완전 삭제 | [Plan 39](plans/39_trade_decision_schema_alignment.md:294) | ❌ 미착수 |
| 5 | **E2E test with TradeDecisionEntity creation**: AI agent 통합 완료 후 E2E 테스트에서 실제 `TradeDecisionEntity` 생성 및 `trade_decision_id` 참조 검증 | [Plan 39](plans/39_trade_decision_schema_alignment.md:296) | ❌ 미착수 |

---

## Longer-term (아키텍처 개선 / 안정성)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Soak / recovery / chaos tests**: 장기 실행 안정성, 장애 복구, 비정상 입력 내성 검증 | 여러 Plan | ❌ 미착수 |
| 2 | **Provider failover / fallback hardening**: LLM provider 장애 시 fallback 전략 고도화 (auto-retry, provider 전환) | [Plan 29](plans/29_ai_decision_backend_contract.md:471), [Plan 30](plans/30_runtime_three_agent_smoke.md:555) | ❌ 미착수 |
| 3 | **Replay UX / audit inspection 개선**: Replay Engine UX 개선, audit 로그 검색/필터 고도화 | [Plan 37](plans/37_long_path_end_to_end_integration.md) | ❌ 미착수 |
| 4 | **Event loop gap-fill path `transition_to()` 검토**: `trigger_gap_fill()`이 ExternalEvent persist만 수행. 향후 fill data → order state 반영 경로 필요 여부 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:844) | ❌ 미착수 |
| 5 | **Reconciliation 결과로 PARTIALLY_FILLED 반영 검토**: 현재는 authoritative reflection에서 PARTIALLY_FILLED 제외. 실제 broker 사례 발생 시 재검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:845) | ❌ 미착수 |
| 6 | **Reconciliation Run에 order_id 직접 매핑**: `_resolve_order_for_reflection()`이 broker_order_id/client_order_id로 찾는 방식. 향후 run에 직접 order_id 저장 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:846) | ❌ 미착수 |

---

## Deferred / Nice-to-have (현재 계획 없음)

| # | 항목 | 출처 | 비고 |
|---|------|------|------|
| 1 | KIS 실통신 (real API key + live trading) | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | Paper mode 우선 |
| 2 | 키움증권 Broker Adapter | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md:99) | KIS 우선 |
| 3 | Full reconciliation automation (auto-resolve) | [Plan 10](plans/10.milestone6_broker_contract_reconciliation_alignment.md) | 현재는 minimal recovery hook만 |
| 4 | Real event data ingestion (OpenDART/KRX polling, news feed) | [Plan 12](plans/12.milestone7_broker_capacity_and_event_data.md:428) | v1 제외 |
| 5 | Redis cache layer (rate limit, session cache) | [Enterprise Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | 현재는 in-memory |
| 6 | CI/CD pipeline (K8s, Terraform, GitHub Actions) | [Plan 01](plans/01.dev_infrastructure_plan.md:6) | v1 제외 |
| 7 | Observability stack (metrics, tracing, structured logging, alerting) | [Enterpris`e Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | v1 제외 |

---

## 상태 범례

| 표시 | 의미 |
|------|------|
| ❌ 미착수 | 아직 시작하지 않음 |
| 🔄 검토 중 | 우선순위 평가 중 |
| ✅ 승격됨 | Numbered plan으로 승격됨 (하단 기록 참조) |
| 🗑️ 폐기 | 더 이상 추진하지 않기로 결정 |

## 승격 기록

| 날짜 | 항목 | Plan 번호 | 비고 |
|------|------|-----------|------|
| 2026-05-04 | Auth / RBAC for Inspection API | [Plan 46](plans/46_auth_rbac_inspection_api.md) | Static Bearer token, viewer/admin RBAC, router-level dependency, safe default |
| 2026-05-04 | Auth Policy Hardening (Pre-UI Security Pass) | [Plan 47](plans/47_auth_policy_hardening.md) | Docs/OpenAPI 공개 정책 고정, token/role validation 강화, 운영 문서 정리 |
| 2026-05-05 | Admin UI Phase 1 (Read-Only Operations Dashboard) | [Plan 48](plans/48_admin_ui_phase1.md) | Vite + React + TypeScript + Pico CSS SPA. FastAPI static serve. 5 screens. sessionStorage token. Phase 1 read-only. |
| 2026-05-05 | Admin UI Smoke / Component Test Hardening | [Plan 49](plans/49_admin_ui_test_hardening.md) | Vitest + RTL + jsdom. 24 tests (P0 16 + P1 8). Auth flow, Dashboard/OrdersView smoke, common components. URL+Method 분기 명확화. |
| 2026-05-05 | Admin UI Test Coverage Phase 2 | [Plan 50](plans/50_admin_ui_test_coverage_phase2.md) | P0 19개 + P1 7개 = 26개 신규 테스트. OrderDetail (7), AccountsView (6), ReconciliationView (6), Layout (4), DecisionsView (3). Fixture 8종 추가. 총 50 tests. |
| 2026-05-05 | Admin UI Operations Workflow Enhancements (P0) | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | OrdersView filter/search, OrderDetail→Decisions drill-down, ReconciliationView quick-filter+lock 강조, Dashboard signal+drill-down. 8개 신규 테스트. 총 58 tests. Backend API 변경 없음. |
| 2026-05-05 | Admin UI Phase 1.5 (Decisions / Accounts UX Completion) | [Plan 52](plans/52_admin_ui_phase1_5.md) | DecisionsView detail panel + context lazy-load (stale guard) + side/symbol/confidence filter + empty placeholder. AccountsView search/type filter + detail clarity + filter-reset policy. DataTable selectedKey prop. 12개 신규 테스트. 총 69 tests. Backend API 변경 없음. |
